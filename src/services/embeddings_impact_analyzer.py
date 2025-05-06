import logging
import anthropic
import json
import re
import asyncio
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict

from src.services.embeddings_service import EmbeddingsService
from src.models.practice_groups import PracticeGroups, PracticeGroupRelevance
from src.models.agency_types import AgencyTypes


@dataclass
class AgencyImpact:
    """Represents specific impact on local agencies"""
    agency_type: str
    impact_type: str
    description: str
    deadline: Optional[datetime] = None
    requirements: List[str] = None


@dataclass
class ChangeAnalysis:
    """Represents analysis of a legislative change"""
    summary: str
    impacts: List[AgencyImpact]
    practice_groups: List[Dict[str, str]]
    action_items: List[str]
    deadlines: List[Dict[str, Any]]
    requirements: List[str]


@dataclass
class ClassificationResult:
    """Stores the results of impact classification."""
    change_id: str
    has_impact: bool
    impact_type: str  # "direct", "indirect", or "none"
    method: str  # "direct_mention", "embedding_similarity", "domain_heuristic"
    confidence: float
    detected_agencies: List[str]
    similarity_scores: Dict[str, float]
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "change_id": self.change_id,
            "has_impact": self.has_impact,
            "impact_type": self.impact_type,
            "method": self.method,
            "confidence": self.confidence,
            "detected_agencies": self.detected_agencies,
            "similarity_scores": self.similarity_scores,
            "timestamp": self.timestamp.isoformat()
        }

    def log_message(self) -> str:
        """Generate detailed log message."""
        agencies_str = ", ".join(self.detected_agencies) if self.detected_agencies else "None"
        similarities_str = ", ".join([f"{k}: {v:.4f}" for k, v in self.similarity_scores.items()]) if self.similarity_scores else "N/A"

        return (f"Change {self.change_id} - Classification: {self.impact_type.upper()} impact, "
                f"Method: {self.method}, Confidence: {self.confidence:.4f}, "
                f"Agencies: {agencies_str}, Similarities: {similarities_str}")


class EmbeddingsImpactAnalyzer:
    """
    Enhanced impact analyzer that uses:
    1. Agency detection pre-filter to immediately identify explicit agency mentions
    2. Multi-class embedding classification to distinguish direct, indirect, and no impacts
    3. LLM for detailed analysis of changes that potentially impact local agencies
    """

    def __init__(
        self, 
        openai_client, 
        practice_groups_data: PracticeGroups,
        embedding_model="text-embedding-3-large", 
        llm_model="gpt-4.1-2025-04-14", 
        anthropic_client=None,
        max_concurrency=3,  # New parameter for controlling parallel requests
        max_retries=3       # New parameter for retry attempts
    ):
        self.logger = logging.getLogger(__name__)
        self.openai_client = openai_client
        self.anthropic_client = anthropic_client
        self.practice_groups = practice_groups_data
        self.agency_types = AgencyTypes()

        # Set up embedding service
        self.embedding_model = embedding_model
        self.embeddings_service = EmbeddingsService(
            openai_client,
            embedding_model=embedding_model,
            embedding_dimensions=768  # Smaller dimensions are sufficient for classification
        )

        # Set up LLM model for detailed analysis
        self.llm_model = llm_model
        self.use_anthropic = llm_model.startswith("claude")

        # Thresholds for classification 
        self.direct_impact_threshold = 0.65
        self.indirect_impact_threshold = 0.60

        # Initialize embeddings to None (will be loaded on first use)
        self.direct_impact_embedding = None
        self.indirect_impact_embedding = None
        self.no_impact_embedding = None

        # For backward compatibility
        self.impact_threshold = 0.60
        self.impact_embedding = None
        self.no_impact_embedding = None

        # List of practice groups that signal likely local agency impacts
        self.local_agency_practice_groups = [
            "Municipal", "Facilities and Business", "Public Finance", 
            "Charter Schools", "School District", "Student", "Special Education",
            "Governance"
        ]

        # New parameters for parallelization
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries

        self.logger.info(f"Initialized Enhanced EmbeddingsImpactAnalyzer with embedding model: {embedding_model}, LLM model: {llm_model}, max_concurrency: {max_concurrency}")

    async def analyze_changes(
        self,
        skeleton: Dict[str, Any],
        progress_handler=None
    ) -> Dict[str, Any]:
        """
        Enhanced analysis of changes with parallelization:
        1. Multi-class classification to determine impact type (direct/indirect/none)
        2. Detailed LLM analysis only for changes with potential impacts
        3. Process multiple changes in parallel with controlled concurrency
        """
        try:
            total_changes = len(skeleton["changes"])

            if progress_handler:
                progress_handler.update_progress(
                    5,  # Step 5 for impact analysis
                    f"Starting enhanced impact analysis with {self.max_concurrency} parallel tasks",
                    0,  # Start at 0
                    total_changes
                )

            # Initialize the embeddings for multi-class classification (one-time)
            await self._initialize_impact_embeddings()

            # Create a semaphore to limit concurrent API calls
            semaphore = asyncio.Semaphore(self.max_concurrency)

            # Track completed changes for progress reporting
            completed_count = 0

            # Create a lock for thread-safe progress updates
            progress_lock = asyncio.Lock()

            # Store classification results for logging and analysis
            classification_results = []

            # Define the worker function that processes a single change
            async def process_change(i, change):
                nonlocal completed_count

                # Acquire semaphore to limit concurrency
                async with semaphore:
                    try:
                        current_change = i + 1  # Human-readable count (1-based)
                        change_id = change['id']

                        # Get bill sections for this change
                        sections = self._get_linked_sections(change, skeleton)
                        code_mods = self._get_code_modifications(change, skeleton)
                        change["bill_section_details"] = sections

                        # Update progress with task starting
                        async with progress_lock:
                            if progress_handler:
                                # Include the digest text preview for better context
                                digest_preview = change['digest_text'][:60] + "..." if len(change['digest_text']) > 60 else change['digest_text']
                                progress_handler.update_substep(
                                    completed_count,
                                    f"Processing change {current_change}/{total_changes}: {digest_preview}"
                                )

                        # Enhanced classification with impact type determination
                        classification = await self._classify_impact_type(change, sections)

                        # Log additional details for debugging model differences
                        self.logger.info(f"MODEL: {self.llm_model}, Change {change_id}: has_impact={classification['has_impact']}, type={classification['impact_type']}, method={classification['method']}, confidence={classification['confidence']:.4f}")

                        # Create ClassificationResult for logging and tracking
                        result = ClassificationResult(
                            change_id=change_id,
                            has_impact=classification["has_impact"],
                            impact_type=classification["impact_type"],
                            method=classification["method"],
                            confidence=classification["confidence"],
                            detected_agencies=classification["agencies"],
                            similarity_scores=classification.get("similarities", {})
                        )

                        # Log the detailed classification result
                        self.logger.info(result.log_message())

                        # Update the change object with classification data
                        change["impacts_local_agencies"] = classification["has_impact"]
                        change["impact_type"] = classification["impact_type"]
                        change["classification_method"] = classification["method"]
                        change["classification_confidence"] = classification["confidence"]

                        # If agencies were detected directly, store them
                        if classification["agencies"]:
                            change["local_agencies_impacted"] = classification["agencies"]

                        # EXPLICIT CHECK: Detailed LLM analysis only if potentially impacts local agencies
                        if classification["has_impact"] == True:  # Explicitly check for True
                            self.logger.info(f"Change {change_id} classified as {classification['impact_type']} impact - proceeding with LLM analysis")

                            # Make sure is_digest_only flag is not set
                            change["is_digest_only"] = False

                            # With exponential backoff retry for LLM analysis
                            retry_count = 0
                            max_retries = self.max_retries
                            retry_delay = 1  # Initial delay in seconds

                            while True:
                                try:
                                    # LLM identifies both practice groups and impacted agencies
                                    analysis = await self._analyze_change_with_llm(change, sections, code_mods, skeleton)
                                    self._update_change_with_analysis(change, analysis)

                                    # Apply post-processing to handle inconsistencies
                                    self._apply_heuristic_corrections(change)
                                    break  # Success, exit retry loop

                                except Exception as e:
                                    retry_count += 1

                                    # Check if we should retry
                                    if retry_count <= max_retries:
                                        # If it's a rate limit or similar transient error
                                        is_rate_limit = any(
                                            err in str(e).lower() 
                                            for err in ["rate limit", "too many requests", "capacity", "overloaded", "timeout"]
                                        )

                                        if is_rate_limit:
                                            self.logger.warning(
                                                f"Rate limit hit for change {change_id}, retry {retry_count}/{max_retries} "
                                                f"after {retry_delay}s delay"
                                            )
                                            await asyncio.sleep(retry_delay)
                                            # Exponential backoff with jitter
                                            retry_delay = min(retry_delay * 2 * (0.5 + 0.5 * (await asyncio.to_thread(float, str(hash(change_id))))), 60)
                                        else:
                                            # For other errors, retry with shorter delay
                                            self.logger.warning(
                                                f"Error analyzing change {change_id}, retry {retry_count}/{max_retries} "
                                                f"after {retry_delay}s delay: {str(e)}"
                                            )
                                            await asyncio.sleep(1)  # Short delay for non-rate-limit errors
                                    else:
                                        self.logger.error(f"Failed to analyze change {change_id} after {max_retries} retries: {str(e)}")
                                        # Create a minimal analysis as fallback
                                        self._create_minimal_analysis(change)
                                        # Add error information
                                        change["analysis_error"] = str(e)
                                        break  # Exit retry loop after max retries
                        else:
                            self.logger.info(f"Change {change_id} has no impact on local agencies - SKIPPING LLM analysis")
                            # For non-impacted changes, create minimal analysis without LLM
                            self._create_minimal_analysis(change)

                            # ENSURE digest text is used and flag is set
                            change["substantive_change"] = "(Legislative Counsel's Digest) " + change["digest_text"]
                            change["is_digest_only"] = True  # Ensure flag is set
                            self.logger.info(f"Setting is_digest_only=True for change {change_id}")

                            # Double check no accidental impact flag
                            change["impacts_local_agencies"] = False

                        # Add result to classification results list
                        async with progress_lock:
                            classification_results.append(result)

                            # Update progress counter and UI
                            completed_count += 1
                            if progress_handler:
                                # Get the count of affected agencies for the status message
                                agency_count = len(change.get("local_agencies_impacted", []))
                                impact_type = classification["impact_type"].upper()

                                if classification["has_impact"]:
                                    agency_msg = f"{agency_count} agencies affected ({impact_type} impact)"
                                else:
                                    agency_msg = "No local agency impact (using digest only)"

                                progress_handler.update_substep(
                                    completed_count,
                                    f"Completed change {completed_count}/{total_changes} ({agency_msg})"
                                )

                                # Also update the main progress
                                progress_handler.update_progress(
                                    5,  # Step 5 for impact analysis
                                    f"Analyzing impacts with embeddings and AI ({completed_count}/{total_changes})",
                                    completed_count,
                                    total_changes
                                )

                        # Before returning, double check the is_digest_only flag is consistent
                        if not change.get("impacts_local_agencies", False):
                            if not change.get("is_digest_only", False):
                                self.logger.warning(f"Inconsistency detected: Change {change_id} has no impact but is_digest_only=False - fixing")
                                change["is_digest_only"] = True
                        else:
                            if change.get("is_digest_only", False):
                                self.logger.warning(f"Inconsistency detected: Change {change_id} has impact but is_digest_only=True - fixing")
                                change["is_digest_only"] = False

                        # Log final state
                        self.logger.info(f"Final state for change {change_id}: impacts_local_agencies={change.get('impacts_local_agencies', False)}, is_digest_only={change.get('is_digest_only', False)}")

                        # ADD THIS LINE: Ensure consistency between impact classification and practice group assignment
                        self._ensure_impact_practice_group_consistency(change)

                        return result
                    except Exception as e:
                        self.logger.error(f"Error processing change {change.get('id', f'index_{i}')}: {str(e)}")
                        # Create minimal analysis as fallback in case of error
                        self._create_minimal_analysis(change)
                        change["analysis_error"] = str(e)

                        # Update progress even on error
                        async with progress_lock:
                            completed_count += 1
                            if progress_handler:
                                progress_handler.update_substep(
                                    completed_count,
                                    f"Error processing change {i+1}/{total_changes}: {str(e)[:50]}..."
                                )

                        # Still return a result object for tracking
                        return ClassificationResult(
                            change_id=change.get('id', f'index_{i}'),
                            has_impact=False,
                            impact_type="none",
                            method="error",
                            confidence=0.0,
                            detected_agencies=[],
                            similarity_scores={}
                        )

            # Create tasks for each change
            tasks = [
                process_change(i, change) 
                for i, change in enumerate(skeleton["changes"])
            ]

            # Execute all tasks in parallel with proper concurrency control
            await asyncio.gather(*tasks)

            # Log all classification results for later analysis
            self._log_classification_summary(classification_results)

            # Update overall metadata of the skeleton
            self._update_skeleton_metadata(skeleton)

            if progress_handler:
                progress_handler.update_progress(
                    5,  # Step 5 for impact analysis
                    f"Impact analysis complete ({total_changes}/{total_changes})",
                    total_changes,  # All changes processed
                    total_changes
                )

            return skeleton

        except Exception as e:
            self.logger.error(f"Error analyzing changes: {str(e)}")
            raise

    def _ensure_impact_practice_group_consistency(self, change: Dict[str, Any]) -> None:
        """
        Ensure consistency between impact classification and practice group assignment.
        If a change impacts local agencies but has no practice groups, add a default.
        If a change has no impact but has practice groups, make adjustments.
        """
        # Case 1: Change has local impact but no practice groups
        if change.get("impacts_local_agencies", False) and (not change.get("practice_groups") or len(change.get("practice_groups", [])) == 0):
            # Based on affected agencies, add default practice group
            agencies = change.get("local_agencies_impacted", [])

            # Law enforcement agencies typically fall under Municipal
            if "City" in agencies or "County" in agencies:
                if any(term in change.get("digest_text", "").lower() for term in ["law enforcement", "police", "sheriff", "alert"]):
                    self.logger.info(f"Adding Municipal practice group for law enforcement-related change {change.get('id')}")
                    change["practice_groups"] = [{
                        "name": "Municipal",
                        "relevance": "primary",
                        "justification": "This change affects local law enforcement agencies operated by cities and counties."
                    }]

        # Case 2: Change has no impact but has practice groups that would normally suggest impact
        if not change.get("impacts_local_agencies", True) and change.get("practice_groups"):
            # Check if any practice group would normally indicate local impact
            has_local_impact_groups = False
            for pg in change.get("practice_groups", []):
                if pg.get("name") in self.local_agency_practice_groups:
                    has_local_impact_groups = True
                    break

            # If it has practice groups that normally indicate impact but is marked as no impact,
            # ensure we log this inconsistency and modify the practice groups
            if has_local_impact_groups:
                self.logger.warning(f"Inconsistency: Change {change.get('id')} has practice groups suggesting impact but is marked as no impact")

                # Keep only practice groups that don't suggest local impact
                updated_groups = []
                for pg in change.get("practice_groups", []):
                    if pg.get("name") not in self.local_agency_practice_groups:
                        updated_groups.append(pg)

                # Update the practice groups list
                change["practice_groups"] = updated_groups
                
    def _detect_agency_mentions(self, text: str) -> List[str]:
        """
        Detect mentions of local agencies in text with improved accuracy to avoid false positives.

        Args:
            text: The text to analyze for agency mentions

        Returns:
            List of detected agency types
        """
        detected_agencies = set()

        # Skip detection for standard bill effective date clauses
        if any(pattern in text.lower() for pattern in [
            "this act is a bill providing for appropriations related to the budget bill",
            "to take effect immediately as a bill providing for appropriations",
            "this bill would declare that it is to take effect immediately",
            "to take effect immediately"
        ]):
            self.logger.info("Detected standard bill effective date clause - skipping agency detection")
            return []

        # Normalize text for case-insensitive matching
        text_lower = text.lower()

        # Specific check for law enforcement terms
        law_enforcement_terms = [
            "law enforcement agency", "police department", "sheriff", "local police", 
            "county sheriff", "city police", "local law enforcement", "peace officer",
            "ebony alert", "silver alert", "amber alert", "missing person"
        ]

        # If law enforcement terms are found, add City and County as affected agencies
        for term in law_enforcement_terms:
            if term in text_lower:
                self.logger.info(f"Detected law enforcement term '{term}' - adding City and County agencies")
                detected_agencies.add("City")
                detected_agencies.add("County")
                break

        # Define additional agency-related terms to look for
        agency_related_terms = [
            "local agency", "local government", "local jurisdiction", 
            "public agency", "public entity", "public authority",
            "municipal", "municipality", "cities", "towns",
            "counties", "board of supervisors", "special district",
            "school board", "education", "unified district",
            "community college", "charter school", "local educational agency"
        ]

        # Check if any of these terms are present
        found_generic_agency = False
        for term in agency_related_terms:
            if term in text_lower:
                found_generic_agency = True
                break

        # Get a list of words for more precise matching
        words = re.findall(r'\b\w+\b', text_lower)

        # Check for each agency type
        for name, agency in self.agency_types.agency_types.items():
            # Skip the "No Local Agency Impact" type for detection purposes
            if name == "No Local Agency Impact":
                continue

            # Only match complete agency names, not parts
            agency_name_lower = name.lower()
            if agency_name_lower in text_lower:
                # Verify it's not just part of another word
                name_parts = agency_name_lower.split()
                consecutive_parts = True

                for i in range(len(words) - len(name_parts) + 1):
                    if words[i:i+len(name_parts)] == name_parts:
                        detected_agencies.add(name)
                        consecutive_parts = True
                        break

                if consecutive_parts:
                    continue

            # Check for keywords associated with this agency type (with more precise matching)
            for keyword in agency.keywords:
                keyword_lower = keyword.lower()

                # Skip short keywords (less than 5 chars) to avoid false positives
                if len(keyword_lower) < 5:
                    continue

                # Check for the keyword as a complete word or phrase
                if keyword_lower in text_lower:
                    # Verify it's a complete word/phrase
                    keyword_parts = keyword_lower.split()
                    for i in range(len(words) - len(keyword_parts) + 1):
                        if words[i:i+len(keyword_parts)] == keyword_parts:
                            detected_agencies.add(name)
                            break

        # If we found generic agency terms but no specific agencies, add common default agencies
        if found_generic_agency and not detected_agencies:
            detected_agencies.add("City")
            detected_agencies.add("County")

        # Log the detection results
        if detected_agencies:
            self.logger.info(f"Detected agencies in text: {detected_agencies}")
        else:
            self.logger.info("No specific agencies detected in text")

        return list(detected_agencies)

    def _get_plural_form(self, name: str) -> Optional[str]:
        """Get plural form of an agency name."""
        if name == "city":
            return "cities"
        elif name == "county":
            return "counties"
        elif name.endswith("y"):
            return name[:-1] + "ies"
        elif name.endswith("s"):
            return name  # Already plural
        else:
            return name + "s"

    async def _initialize_impact_embeddings(self):
        """Initialize the embeddings for multi-class impact classification."""
        if self.direct_impact_embedding is None:
            # Define text descriptions for multi-class classification
            direct_impact_text = """
            The legislative change has direct impacts on local public agencies like cities, counties, 
            school districts, community colleges, special districts, or joint powers authorities. 
            The change explicitly names local agencies and creates new requirements, modifies existing obligations, 
            affects funding, changes reporting requirements, alters deadlines, impacts operations, 
            modifies authority, or changes permitted activities for local agencies.

            The bill contains direct references to local agencies with explicit requirements or changes
            that local agencies must implement. The impact is clear and immediate, with named responsibilities
            for local government entities. Local officials must take specific actions as a direct result of this change.
            """

            indirect_impact_text = """
            The legislative change has indirect impacts on local public agencies. While the bill may not explicitly
            name local agencies, it modifies state programs, funding formulas, or regulations that will affect
            local agencies. The change creates downstream effects that local agencies will experience.

            Examples include changes to state funding formulas that affect money distributed to local agencies,
            modifications to state regulations that local agencies must enforce, or changes to programs that
            local agencies participate in. The bill primarily targets state agencies, but the effects will
            eventually reach local governments through existing relationships, programs, or channels.
            """

            no_impact_text = """
            The legislative change has absolutely no impact on local public agencies. The change only affects 
            state agencies, private entities, or individuals. It creates no new requirements, obligations, 
            funding changes, deadlines, operational impacts, or any other effects for cities, counties, 
            school districts, community colleges, special districts, or other local government entities.

            The bill makes no mention of local governments, contains no provisions that local agencies must
            implement or comply with, provides no funding that flows to local agencies, and does not modify
            any programs that local agencies participate in.

            The change operates entirely at the state level, with state agencies as the sole governmental 
            entities affected by its provisions. No local officials have any responsibilities under this change,
            and no local services, functions, or authorities are affected in any way.
            """

            # Generate embeddings for multi-class classification
            self.logger.info("Generating embeddings for multi-class impact classification")
            self.direct_impact_embedding = await self.embeddings_service.get_embedding(direct_impact_text)
            self.indirect_impact_embedding = await self.embeddings_service.get_embedding(indirect_impact_text)
            self.no_impact_embedding = await self.embeddings_service.get_embedding(no_impact_text)

            # For backward compatibility
            self.impact_embedding = self.direct_impact_embedding

    async def _classify_impact_type(self, change: Dict[str, Any], sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Classify the impact type of a change on local agencies.
        Uses fixed thresholds for consistent behavior across models.
        """
        # Combine text from change and sections for analysis
        combined_text = f"{change['digest_text']} {change.get('existing_law', '')} {change.get('proposed_change', '')}"

        # Add section texts if available (first 1000 chars of each section)
        for section in sections:
            section_text = section.get('text', '')
            if section_text:
                combined_text += f" {section_text[:1000]}"

        # Log combined text length
        self.logger.info(f"Combined text length for classification: {len(combined_text)} chars")

        # 1. First, check for direct agency mentions
        detected_agencies = self._detect_agency_mentions(combined_text)

        # Log detected agencies
        self.logger.info(f"Change {change.get('id', 'unknown')}: detected agencies = {detected_agencies}")

        # Fixed bias to ensure consistency across models
        model_independent_bias = True
        self.logger.info(f"Using model-independent bias: {model_independent_bias}")

        if detected_agencies:
            self.logger.info(f"Change {change['id']} contains direct agency mentions: {detected_agencies} - classifying as direct impact")
            return {
                "has_impact": True,
                "impact_type": "direct",
                "agencies": detected_agencies,
                "method": "direct_mention",
                "confidence": 0.95,  # High confidence for direct mentions
                "similarities": {}  # No embedding similarity used
            }

        # 2. Keyword-based approach as reliable fallback
        if self._has_practice_area_keywords(change, combined_text):
            self.logger.info(f"Change {change['id']} has practice area keywords suggesting local impact")
            return {
                "has_impact": True,
                "impact_type": "indirect",
                "agencies": ["City", "County"],  # Default agencies
                "method": "practice_area_heuristic",
                "confidence": 0.75,
                "similarities": {}
            }

        # 3. Embedding classification with fixed thresholds
        text_embedding = await self.embeddings_service.get_embedding(combined_text)

        # Calculate similarity with reference embeddings
        direct_similarity = self.embeddings_service.cosine_similarity(text_embedding, self.direct_impact_embedding)
        indirect_similarity = self.embeddings_service.cosine_similarity(text_embedding, self.indirect_impact_embedding)
        no_impact_similarity = self.embeddings_service.cosine_similarity(text_embedding, self.no_impact_embedding)

        similarities = {
            "direct": direct_similarity,
            "indirect": indirect_similarity, 
            "none": no_impact_similarity
        }

        self.logger.info(f"Change {change['id']} - Similarity scores: Direct: {direct_similarity:.4f}, "
                        f"Indirect: {indirect_similarity:.4f}, None: {no_impact_similarity:.4f}")

        # FIXED THRESHOLDS for consistent behavior
        direct_threshold = 0.55
        indirect_threshold = 0.53

        # Apply fixed bias adjustments 
        if model_independent_bias:
            direct_similarity += 0.05
            indirect_similarity += 0.03
            self.logger.info(f"After bias: Direct: {direct_similarity:.4f}, Indirect: {indirect_similarity:.4f}")

        # Make decision based on highest similarity that exceeds threshold
        if direct_similarity >= direct_threshold and direct_similarity >= indirect_similarity and direct_similarity >= no_impact_similarity:
            impact_type = "direct"
            has_impact = True
            confidence = direct_similarity
        elif indirect_similarity >= indirect_threshold and indirect_similarity >= no_impact_similarity:
            impact_type = "indirect"
            has_impact = True
            confidence = indirect_similarity
        else:
            impact_type = "none"
            has_impact = False
            confidence = no_impact_similarity

        # Special case for transportation (fallback)
        if impact_type == "none" and self._is_transportation_related(change):
            self.logger.info(f"Change {change['id']} appears transportation-related - classifying as indirect impact")
            return {
                "has_impact": True,
                "impact_type": "indirect",
                "agencies": ["City", "County", "Special District"],
                "method": "domain_heuristic",
                "confidence": 0.75,
                "similarities": similarities
            }

        self.logger.info(f"Change {change['id']} classified as '{impact_type}' impact with confidence {confidence:.4f}")

        return {
            "has_impact": has_impact,
            "impact_type": impact_type,
            "agencies": [],
            "method": "embedding_similarity",
            "confidence": confidence,
            "similarities": similarities
        }

    def _has_practice_area_keywords(self, change: Dict[str, Any], text: str) -> bool:
        """Check if text contains keywords associated with practice areas that typically impact local agencies"""
        text_lower = text.lower()

        # Keywords associated with local agency impacts
        local_impact_keywords = [
            "local agency", "local government", "local jurisdiction", "local authority",
            "city", "county", "municipality", "municipal", "special district",
            "school district", "community college", "charter school",
            "public agency", "public entity", "jpa", "joint powers",
            "local control", "local funding", "local program", 
            "local requirement", "local mandate", "local board",
            "governing board", "ordinance", "resolution", "permits", "license",
            "public works", "public facility", "public building",
            "zoning", "land use", "planning", "ceqa", "environmental review"
        ]

        # Check for keyword matches
        matches = [keyword for keyword in local_impact_keywords if keyword in text_lower]
        if matches:
            self.logger.info(f"Found practice area keywords: {matches}")
            return True
        return False
        
    # Add this helper method to detect practice area keywords
    def _has_practice_area_keywords(self, change: Dict[str, Any], text: str) -> bool:
        """Check if text contains keywords associated with practice areas that typically impact local agencies"""
        text_lower = text.lower()

        # Keywords associated with local agency impacts
        local_impact_keywords = [
            "local agency", "local government", "local jurisdiction", "local authority",
            "city", "county", "municipality", "municipal", "special district",
            "school district", "community college", "charter school",
            "public agency", "public entity", "jpa", "joint powers",
            "local control", "local funding", "local program", 
            "local requirement", "local mandate", "local board",
            "governing board", "ordinance", "resolution", "permits", "license",
            "public works", "public facility", "public building",
            "zoning", "land use", "planning", "ceqa", "environmental review"
        ]

        return any(keyword in text_lower for keyword in local_impact_keywords)

    # Add this helper method to detect practice area keywords
    def _has_practice_area_keywords(self, change: Dict[str, Any], text: str) -> bool:
        """Check if text contains keywords associated with practice areas that typically impact local agencies"""
        text_lower = text.lower()

        # Keywords associated with local agency impacts
        local_impact_keywords = [
            "local agency", "local government", "local jurisdiction", "local authority",
            "city", "county", "municipality", "municipal", "special district",
            "school district", "community college", "charter school",
            "public agency", "public entity", "jpa", "joint powers",
            "local control", "local funding", "local program", 
            "local requirement", "local mandate", "local board",
            "governing board", "ordinance", "resolution", "permits", "license",
            "public works", "public facility", "public building",
            "zoning", "land use", "planning", "ceqa", "environmental review"
        ]

        return any(keyword in text_lower for keyword in local_impact_keywords)

    def _log_classification_summary(self, results: List[ClassificationResult]):
        """Log summary statistics about classification results."""
        total = len(results)
        impact_count = sum(1 for r in results if r.has_impact)
        direct_count = sum(1 for r in results if r.impact_type == "direct")
        indirect_count = sum(1 for r in results if r.impact_type == "indirect")

        # Count by method
        method_counts = {}
        for r in results:
            method_counts[r.method] = method_counts.get(r.method, 0) + 1

        # Calculate average confidence
        avg_confidence = sum(r.confidence for r in results) / total if total > 0 else 0

        self.logger.info(f"Classification Summary - Total: {total}, Has Impact: {impact_count} ({direct_count} direct, {indirect_count} indirect)")
        self.logger.info(f"Methods: {method_counts}, Avg Confidence: {avg_confidence:.4f}")

    # For backward compatibility, provide the older binary classification method
    async def _binary_classification(self, change: Dict[str, Any], sections: List[Dict[str, Any]]) -> bool:
        """
        Backward compatibility method that calls _classify_impact_type and returns a boolean.

        Args:
            change: The change object to analyze
            sections: Bill sections implementing this change

        Returns:
            bool: True if the change potentially impacts local agencies, False otherwise
        """
        classification = await self._classify_impact_type(change, sections)
        return classification["has_impact"]

    # The following methods are retained from the original implementation
    # with minimal modifications for compatibility

    def _apply_heuristic_corrections(self, change: Dict[str, Any]) -> None:
        """
        Apply heuristic corrections to address inconsistencies while respecting LLM decisions.
        """
        # Check if LLM explicitly determined no impact
        llm_says_no_impact = False
        impact_desc = change.get("local_agency_impact", "")

        if impact_desc and any(no_impact_phrase in impact_desc.lower() for no_impact_phrase in [
            "no direct impact", 
            "no impact on local agencies",
            "does not impact local agencies",
            "no local agencies identified",
            "are no direct or indirect impacts"
        ]):
            llm_says_no_impact = True
            self.logger.info(f"LLM explicitly determined no local agency impact for change {change.get('id')}")

        # If LLM says no impact, don't override with heuristics
        if llm_says_no_impact:
            # Ensure the flags and lists are consistent with "no impact"
            change["impacts_local_agencies"] = False
            change["local_agencies_impacted"] = []
            change["is_digest_only"] = True

            # Remove any agency notice that got added incorrectly
            if "While specific impacts are not detailed" in change.get("local_agency_impact", ""):
                change["local_agency_impact"] = "No direct impact on local agencies."

            self.logger.info(f"Respecting LLM's determination of no impact for change {change.get('id')}")
            return

        # Original heuristic code remains unchanged for cases where LLM didn't explicitly deny impact
        if not change.get("local_agencies_impacted") and change.get("practice_groups"):
            local_group_identified = False
            primary_local_groups = []

            # Check if any practice groups signal local agency involvement
            for group in change.get("practice_groups", []):
                if group.get("name") in self.local_agency_practice_groups:
                    local_group_identified = True
                    if group.get("relevance") == "primary":
                        primary_local_groups.append(group.get("name"))

            # If we have local-focused practice groups but no identified agencies, add defaults
            if local_group_identified:
                self.logger.info(f"Applying heuristic correction for change {change.get('id')}: "
                                f"Practice groups suggest local impact but no agencies identified")

                default_agencies = []

                # Add specific agencies based on practice group
                if "Municipal" in primary_local_groups:
                    default_agencies.extend(["City", "County"])

                if "Public Finance" in primary_local_groups:
                    default_agencies.extend(["City", "County", "Special District"])

                if "Facilities and Business" in primary_local_groups:
                    default_agencies.extend(["City", "County", "School District"])

                if "Charter Schools" in primary_local_groups or "School District" in primary_local_groups:
                    default_agencies.extend(["School District", "Charter School"])

                if "Governance" in primary_local_groups:
                    default_agencies.extend(["City", "County"])

                # If we've identified default agencies, update the change
                if default_agencies:
                    # Remove duplicates and sort
                    default_agencies = sorted(list(set(default_agencies)))

                    change["local_agencies_impacted"] = default_agencies
                    change["impacts_local_agencies"] = True

                    # Add an explanation to the impact description
                    original_impact = change.get("local_agency_impact", "No direct impact on local agencies.")

                    if "No direct impact" in original_impact:
                        impact_desc = f"While specific impacts are not detailed in the bill text, this change likely affects {', '.join(default_agencies)} based on the practice groups involved. Further legal analysis may be needed to determine specific compliance requirements."
                    else:
                        impact_desc = original_impact

                    change["local_agency_impact"] = impact_desc

                    self.logger.info(f"Added default agencies {default_agencies} based on practice groups")

        # Check for transportation-related content
        if not change.get("local_agencies_impacted") and self._is_transportation_related(change):
            self.logger.info(f"Transportation-related change detected for {change.get('id')}, adding default agencies")
            change["local_agencies_impacted"] = ["City", "County", "Special District"]
            change["impacts_local_agencies"] = True

            # Add an explanation
            change["local_agency_impact"] = ("This transportation-related change may affect City, County, and "
                                          "Special District agencies involved in transportation infrastructure "
                                          "and services. Further analysis is recommended to determine specific impacts.")

    def _is_transportation_related(self, change: Dict[str, Any]) -> bool:
        """Check if the change is related to transportation"""
        combined_text = f"{change['digest_text']} {change.get('existing_law', '')} {change.get('proposed_change', '')}"

        transportation_keywords = [
            "transportation", "transit", "highway", "road", "street", "traffic", "bicycle", "pedestrian",
            "freeway", "corridor", "active transportation", "public transportation", "rail", "vehicle",
            "congestion", "high-speed rail", "infrastructure", "bridge", "caltrans", "department of transportation"
        ]

        text_lower = combined_text.lower()
        matches = [keyword for keyword in transportation_keywords if keyword in text_lower]

        # If we have multiple transportation keywords, it's transportation-related
        return len(matches) >= 2

    async def _analyze_change_with_llm(
        self,
        change: Dict[str, Any],
        sections: List[Dict[str, Any]],
        code_mods: List[Dict[str, Any]],
        skeleton: Dict[str, Any]
    ) -> ChangeAnalysis:
        """
        Generate comprehensive analysis of a change using LLM, with streaming for Claude 3.7
        """
        # Updated prompt to include practice group and agency identification
        prompt = self._build_comprehensive_prompt(change, sections, code_mods)

        # Determine which API to use
        if self.use_anthropic:
            # Using Anthropic API
            system_prompt = (
                "You are a legal expert analyzing legislative changes affecting local public agencies. "
                "Your task includes identifying affected agency types, relevant practice groups, and analyzing impacts. "
                "Focus on practical implications, compliance requirements, and deadlines. "
                "Be thorough in identifying all potential local agency impacts, even if they are indirect. "
                "Provide concise, action-oriented analysis in JSON format."
            )

            # Check if we're using Claude 3.7
            is_claude_3_7 = "claude-3-7" in self.llm_model.lower()

            self.logger.info(f"Anthropic SDK version: {anthropic.__version__}")
            self.logger.info(f"Using model: {self.llm_model}")

            try:
                # Base parameters that work for all Claude models
                params = {
                    "model": self.llm_model,
                    "max_tokens": 64000,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 1  # Required for extended thinking
                }

                # Add extended thinking for Claude 3.7
                if is_claude_3_7:
                    params["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": 16000
                    }
                    self.logger.info("Using streaming with extended thinking for Claude 3.7")

                    # Use streaming for Claude 3.7 with extended thinking
                    response_content = ""
                    async with self.anthropic_client.messages.stream(**params) as stream:
                        async for chunk in stream:
                            if hasattr(chunk, 'type') and chunk.type == "content_block_delta":
                                if chunk.delta.type == "text_delta" and hasattr(chunk.delta, 'text'):
                                    response_content += chunk.delta.text

                    # Log successful response
                    self.logger.info(f"Successfully received streamed response from Claude. Content length: {len(response_content)}")
                else:
                    # For non-Claude 3.7 models, just use standard messages API
                    response = await self.anthropic_client.messages.create(**params)

                    # Extract text from response based on its structure
                    response_content = ""
                    if hasattr(response, 'content'):
                        if isinstance(response.content, list):
                            # It's a list of content blocks (most likely)
                            for block in response.content:
                                if hasattr(block, 'type') and block.type == "text":
                                    response_content += block.text
                        else:
                            # It might be a string
                            response_content = response.content

                    # If we still don't have content, try other attributes
                    if not response_content and hasattr(response, 'message'):
                        if hasattr(response.message, 'content'):
                            response_content = response.message.content

                    # Log successful response
                    self.logger.info(f"Successfully received response from Claude. Content length: {len(response_content)}")

            except Exception as e:
                self.logger.error(f"Error using Anthropic API: {str(e)}")
                raise
        else:
            # Using OpenAI API - with improved error handling for o3-mini models
            base_params = {
                "model": self.llm_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a legal expert analyzing legislative changes affecting local public agencies. "
                            "Your task includes identifying affected agency types, relevant practice groups, and analyzing impacts. "
                            "Focus on practical implications, compliance requirements, and deadlines. "
                            "Be thorough in identifying all potential local agency impacts, even if they are indirect. "
                            "Provide concise, action-oriented analysis in JSON format."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "response_format": {"type": "json_object"}
            }

            # Create a copy of base parameters
            params = base_params.copy()

            # Set model-specific parameters
            if "o4-mini" in self.llm_model:
                self.logger.info(f"Using OpenAI API with o4-mini model: {self.llm_model}")
                params["temperature"] = 0.7  # Higher temperature for creative analysis
                params["max_tokens"] = 4000  # Limit response length for efficiency
                # Note: reasoning_effort is only supported in synchronous API, not async
            elif "gpt-4.1" in self.llm_model:
                self.logger.info(f"Using OpenAI API with GPT-4.1: {self.llm_model}")
                params["temperature"] = 0.1  # More precise responses
                params["max_tokens"] = 8000  # Allow longer responses
            else:
                # Default parameters for other models
                self.logger.info(f"Using OpenAI API with default parameters for model: {self.llm_model}")
                params["temperature"] = 0.3
                params["max_tokens"] = 6000

            # Make the API call
            try:
                response = await self.openai_client.chat.completions.create(**params)
                self.logger.info(f"Successfully received response from model {self.llm_model}")
            except Exception as e:
                self.logger.error(f"Error calling OpenAI API with model {self.llm_model}: {str(e)}")
                raise

            # Extract content from OpenAI response
            analysis_data = json.loads(response.choices[0].message.content)

        # If using Anthropic, we need to parse the JSON response here
        if self.use_anthropic:
            # Parse the JSON response from the text
            try:
                # Log the first 100 chars of the response for debugging
                self.logger.info(f"Response content begins with: {response_content[:100]}...")

                # Check if response is empty
                if not response_content:
                    raise ValueError("Empty response from Anthropic API")

                # If response doesn't start with a JSON object, try to extract it
                if not response_content.strip().startswith('{'):
                    # Try to extract JSON content
                    json_start = response_content.find('{')
                    json_end = response_content.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        clean_json = response_content[json_start:json_end]
                        self.logger.info(f"Extracted JSON from position {json_start} to {json_end}")
                        analysis_data = json.loads(clean_json)
                    else:
                        raise ValueError("Could not extract JSON from response")
                else:
                    analysis_data = json.loads(response_content)
            except json.JSONDecodeError:
                # Handle case where response isn't valid JSON
                self.logger.error(f"Invalid JSON response from Claude: {response_content[:200]}...")
                # Try to extract JSON from text response
                json_start = response_content.find('{')
                json_end = response_content.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    try:
                        clean_json = response_content[json_start:json_end]
                        analysis_data = json.loads(clean_json)
                    except:
                        self.logger.error("Failed to extract JSON from Claude response")
                        raise
                else:
                    raise ValueError("Failed to parse JSON response from Claude")

        # Process impact details from JSON (unchanged)
        impacts_list = []
        for impact_dict in analysis_data.get("agency_impacts", []):
            raw_deadline = impact_dict.get("deadline")
            parsed_deadline = None
            if raw_deadline and isinstance(raw_deadline, str):
                try:
                    parsed_deadline = datetime.strptime(raw_deadline, "%Y-%m-%d")
                except ValueError:
                    self.logger.warning(f"Unable to parse deadline '{raw_deadline}' as YYYY-MM-DD.")
                    parsed_deadline = None

            impacts_list.append(
                AgencyImpact(
                    agency_type=impact_dict["agency_type"],
                    impact_type=impact_dict["impact_type"],
                    description=impact_dict["description"],
                    deadline=parsed_deadline,
                    requirements=impact_dict.get("requirements", [])
                )
            )

        # Store the identified local agency types directly in the change object
        change["local_agencies_impacted"] = [impact.agency_type for impact in impacts_list]

        # Update with practice group information from LLM
        practice_groups = []
        for pg in analysis_data.get("practice_groups", []):
            practice_groups.append({
                "name": pg["name"],
                "relevance": pg["relevance"],
                "justification": pg.get("justification", "")
            })

        change["practice_groups"] = practice_groups

        return ChangeAnalysis(
            summary=analysis_data.get("summary", "No summary provided"),
            impacts=impacts_list,
            practice_groups=practice_groups,
            action_items=analysis_data.get("action_items", []),
            deadlines=analysis_data.get("deadlines", []),
            requirements=analysis_data.get("requirements", [])
        )

    def _build_comprehensive_prompt(self, change, sections, code_mods) -> str:
        """
        Build a comprehensive prompt for LLM analysis that includes:
        1. Practice group identification
        2. Agency type identification
        3. Detailed impact analysis
        """
        # Provide the available practice groups
        practice_groups_text = self.practice_groups.get_prompt_text(detail_level="brief")

        # Provide valid agency types
        agency_types_text = "\n".join([
            f"{agency.name}: {agency.description[:100]}..." 
            for agency in self.agency_types.agency_types.values()
        ])

        instruction_block = f"""
You're analyzing a legislative change affecting California state laws to determine:
1. Which LOCAL AGENCIES are impacted (if any), including indirectly
2. Which PRACTICE GROUPS are relevant
3. The SPECIFIC IMPACTS and required actions for affected agencies

## IMPORTANT: LOCAL AGENCY IMPACT DETERMINATION
- A bill impacts local agencies if it creates new requirements, changes duties, affects funding, modifies powers, requires compliance, or changes programs in which local agencies participate
- INDIRECT IMPACTS COUNT: If state-level changes filter down to local agencies (e.g., through funding formulas, programs they participate in, or regulations they must enforce), this counts as impact
- Be thorough in identifying ALL potentially affected local agency types - err on the side of inclusion rather than exclusion
- Even if impacts are minor or potential rather than certain, identify the agency types that might be affected

## AGENCY TYPES (use these exact names)
{agency_types_text}

## PRACTICE GROUPS (use these exact names)
{practice_groups_text}

Return the following JSON structure:
{{
  "summary": "Explanation of change and impacts on local agencies",
  "agency_impacts": [
    {{
      "agency_type": "name from agency types list",
      "impact_type": "type of impact",
      "description": "detailed explanation",
      "deadline": "YYYY-MM-DD or null",
      "requirements": ["req1", "req2"]
    }}
  ],
  "practice_groups": [
    {{
      "name": "name from practice groups list",
      "relevance": "primary or secondary",
      "justification": "why this practice group is relevant"
    }}
  ],
  "action_items": ["action1", "action2"],
  "deadlines": [
    {{
      "date": "YYYY-MM-DD",
      "description": "deadline details",
      "affected_agencies": ["agency types"]
    }}
  ],
  "requirements": ["req1", "req2"]
}}

IMPORTANT: Be thorough in identifying all potential local agency impacts, even minor or indirect ones. If NO local agencies are impacted, return an empty array for agency_impacts.
"""

        section_info = self._format_sections(sections)
        code_mods_text = self._format_code_mods(code_mods)

        return f"""{instruction_block}

Analyze this legislative change and its impact on local public agencies:

Digest Text:
{change['digest_text']}

Bill Sections Implementing This Change:
{section_info}

Code Modifications:
{code_mods_text}

Existing Law:
{change.get('existing_law', '')}

Proposed Changes:
{change.get('proposed_change', '')}
"""

    def _create_minimal_analysis(self, change: Dict[str, Any]) -> None:
        """
        Create minimal analysis for changes with no local agency impact
        """
        # Ensure the substantive_change field has the digest text
        digest_text = change.get("digest_text", "No digest text available.")

        change.update({
            "substantive_change": "(Legislative Counsel's Digest) " + digest_text,
            "local_agency_impact": "No direct impact on local agencies identified.",
            "key_action_items": [],
            "deadlines": [],
            "requirements": [],
            "impacts_local_agencies": False,
            "local_agencies_impacted": [],
            "practice_groups": [],  # Empty practice groups
            "is_digest_only": True  # Explicit flag for digest-only entries
        })

        # Double check the flag is set correctly
        if not change.get("is_digest_only", False):
            self.logger.warning(f"Warning: is_digest_only flag was not set properly for change {change.get('id', 'unknown')} - fixing")
            change["is_digest_only"] = True

    def _format_code_mods(self, mods: List[Dict[str, Any]]) -> str:
        formatted = []
        for mod in mods:
            text = f"{mod['code_name']} Section {mod['section']}:\n"
            text += f"Action: {mod['action']}\n"
            text += f"Context: {mod.get('text','N/A')}\n"
            formatted.append(text)
        return "\n".join(formatted)

    def _update_change_with_analysis(self, change: Dict[str, Any], analysis: ChangeAnalysis) -> None:
        """Update change object with analysis results and ensure consistency"""
        # Original update code
        change.update({
            "substantive_change": analysis.summary,
            "local_agency_impact": self._format_agency_impacts(analysis.impacts),
            "practice_groups": analysis.practice_groups,
            "key_action_items": analysis.action_items,
            "deadlines": analysis.deadlines,
            "requirements": analysis.requirements,
            "impacts_local_agencies": bool(analysis.impacts)
        })

        # Add consistency check based on LLM's impact assessment
        impact_desc = change.get("local_agency_impact", "")

        if any(phrase in impact_desc.lower() for phrase in [
            "no direct impact", 
            "no impact on local agencies",
            "does not impact local agencies",
            "no local agencies identified",
            "are no direct or indirect impacts"
        ]):
            # LLM determined no impact - ensure consistency
            self.logger.info(f"Consistency check: LLM indicates no impact for change {change.get('id')}")
            change["impacts_local_agencies"] = False
            change["local_agencies_impacted"] = []
            change["is_digest_only"] = True
        elif bool(analysis.impacts):
            # LLM found impacts - ensure correct flags
            change["is_digest_only"] = False

    def _format_agency_impacts(self, impacts: List[AgencyImpact]) -> str:
        if not impacts:
            return "No direct impact on local agencies."
        formatted = []
        for impact in impacts:
            text = f"{impact.agency_type}: {impact.description}"
            if impact.deadline:
                text += f" (Deadline: {impact.deadline.strftime('%B %d, %Y')})"
            formatted.append(text)
        return "\n".join(formatted)

    def _update_skeleton_metadata(self, skeleton: Dict[str, Any]) -> None:
        """Update skeleton metadata with analysis results"""
        impacting_changes = [
            c for c in skeleton["changes"]
            if c.get("impacts_local_agencies")
        ]

        # Collect all impacted agency types across all changes
        all_impacted_agencies = set()
        for change in skeleton["changes"]:
            all_impacted_agencies.update(change.get("local_agencies_impacted", []))

        primary_groups = set()
        for change in skeleton["changes"]:
            for group in change.get("practice_groups", []):
                if group.get("relevance") == "primary":
                    primary_groups.add(group["name"])

        skeleton["metadata"].update({
            "has_agency_impacts": bool(impacting_changes),
            "impacting_changes_count": len(impacting_changes),
            "practice_groups_affected": sorted(primary_groups),
            "impacted_agencies": sorted(all_impacted_agencies)
        })

    def _get_linked_sections(self, change: Dict[str, Any], skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get bill sections linked to this change."""
        sections = []

        # Get and normalize section numbers
        section_refs = change.get("bill_sections", [])
        normalized_nums = []

        for ref in section_refs:
            # If it's a string like "Section 7", extract just the number
            if isinstance(ref, str) and "section" in ref.lower():
                match = re.search(r'(\d+)', ref, re.IGNORECASE)
                if match:
                    normalized_nums.append(match.group(1))
            else:
                # If it's already just the number or another format
                normalized_nums.append(str(ref))

        self.logger.info(f"Change {change.get('id')} has normalized section numbers: {normalized_nums}")

        # Get bill sections from skeleton
        bill_sections = skeleton.get("bill_sections", [])

        # For each normalized section number, find matching bill section
        for section_num in normalized_nums:
            found = False
            for section in bill_sections:
                if str(section.get("number")) == section_num:
                    self.logger.info(f"Found section {section_num} with label: {section.get('original_label')}")
                    sections.append({
                        "number": section.get("number"),
                        "text": section.get("text", ""),
                        "original_label": section.get("original_label"),
                        "code_modifications": section.get("code_modifications", [])
                    })
                    found = True
                    break

            if not found:
                self.logger.warning(f"Could not find section {section_num} in bill_sections")

        return sections

    def _get_code_modifications(self, change: Dict[str, Any], skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract code modifications from bill sections associated with a change
        """
        mods = []

        # Get and normalize section numbers from the change
        section_refs = change.get("bill_sections", [])
        normalized_nums = []

        for ref in section_refs:
            # If it's a string like "Section 7", extract just the number
            if isinstance(ref, str) and "section" in ref.lower():
                match = re.search(r'(\d+)', ref, re.IGNORECASE)
                if match:
                    normalized_nums.append(match.group(1))
            else:
                # If it's already just the number or another format
                normalized_nums.append(str(ref))

        # For each normalized section number, find associated code modifications
        for section_num in normalized_nums:
            for section in skeleton.get("bill_sections", []):
                if str(section.get("number")) == section_num:
                    for mod in section.get("code_modifications", []):
                        # Include section text with the modification for context
                        mod_with_context = mod.copy()
                        mod_with_context["text"] = section.get("text", "")[:200]  # First 200 chars for context
                        mods.append(mod_with_context)

        return mods

    def _format_sections(self, sections: List[Dict[str, Any]]) -> str:
        """Format the list of sections for the prompt"""
        formatted = []
        for section in sections:
            text = f"Section {section['number']}:\n"
            text += f"Text: {section['text'][:500]}..." if len(section['text']) > 500 else f"Text: {section['text']}\n"
            if section.get('code_modifications'):
                text += "\nModifies:\n"
                for mod in section['code_modifications']:
                    text += f"- {mod['code_name']} Section {mod['section']} ({mod.get('action', 'unknown')})\n"
            formatted.append(text)
        return "\n".join(formatted)