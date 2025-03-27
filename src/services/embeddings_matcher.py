# embeddings_matcher.py

import logging
import os
import asyncio
import math
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

# If you are using the same "openai_client" approach as in main.py, import that here:
# from main import openai_client

from openai import AsyncOpenAI

aclient = AsyncOpenAI(api_key=OPENAI_API_KEY)

#################################################################
# Utility functions for cosine similarity and asynchronous calls
#################################################################

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    v1 = np.array(vec1, dtype=float)
    v2 = np.array(vec2, dtype=float)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))

async def get_embedding(
    text: str,
    model: str = "text-embedding-3-large"
) -> List[float]:
    """Fetch embedding for a single text string using OpenAI Embeddings API."""
    # Remove line breaks to reduce chance of mismatch
    clean_text = text.replace("\n", " ")
    try:
        # You might already have an async openai client in your code.
        # If so, adapt the call accordingly. For example:
        #
        # embedding_response = await openai_client.embeddings.create(...)
        #
        # Below, we'll show a simple direct usage of openai.Embeddings.
        # If your code patches "openai" for proxies, it should still work.
        response = await aclient.embeddings.create(model=model,
        input=clean_text)
        # Return the embedding vector
        return response["data"][0]["embedding"]
    except Exception as e:
        logging.error(f"Error fetching embedding: {str(e)}")
        return []

async def get_embeddings_for_list(
    texts: List[str],
    model: str = "text-embedding-3-large"
) -> List[List[float]]:
    """
    Fetch embeddings for a list of strings. 
    Calls get_embedding in a simple loop with asyncio.gather for concurrency.
    """
    tasks = []
    for t in texts:
        tasks.append(get_embedding(t, model=model))
    results = await asyncio.gather(*tasks)
    return results


#################################################################
# EmbeddingsMatcher class
#################################################################

class EmbeddingsMatcher:
    """
    A class that uses OpenAI embeddings to:
      1. Match digest items to bill sections
      2. Identify relevant practice groups for each legislative change
      3. Identify local public agency type impacted
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        model: str = "text-embedding-3-large",
        similarity_threshold: float = 0.50,
        practice_group_threshold: float = 0.50,
        local_agency_threshold: float = 0.50
    ):
        """
        :param openai_api_key: Optionally pass your OpenAI API key. 
                               Otherwise, ensure it's set in the environment.
        :param model: Embedding model to use (default is text-embedding-3-large).
        :param similarity_threshold: For section matching; anything below this is ignored.
        :param practice_group_threshold: For picking relevant practice groups.
        :param local_agency_threshold: For picking local public agency type.
        """
        self.logger = logging.getLogger(__name__)

        # If needed, set the OpenAI API key here
        if openai_api_key:
            os.environ["OPENAI_API_KEY"] = openai_api_key
            
        self.model = model
        self.similarity_threshold = similarity_threshold
        self.practice_group_threshold = practice_group_threshold
        self.local_agency_threshold = local_agency_threshold

        # Hard-code the local public agency types to attempt to match
        self._local_agency_types = [
            "School District",
            "Charter School",
            "County Office of Education",
            "Community College",
            "City",
            "County",
            "Special District",
            "Joint Powers Authority"
        ]
        self._local_agency_embeddings: Dict[str, List[float]] = {}

        # We'll store practice group data & embeddings separately (loaded from practice_groups file).
        self._practice_groups: List[Dict[str, str]] = []  # e.g. [{"name": "Facilities and Business", "description": "..."}]
        self._practice_group_embeddings: Dict[str, List[float]] = {}

        self.logger.info("EmbeddingsMatcher initialized.")

    async def prepare_agency_type_embeddings(self):
        """Embed the local public agency type strings once."""
        if self._local_agency_embeddings:
            return  # Already done

        embeddings = await get_embeddings_for_list(self._local_agency_types, model=self.model)
        for agency_type, emb in zip(self._local_agency_types, embeddings):
            self._local_agency_embeddings[agency_type] = emb
        self.logger.info("Local public agency type embeddings prepared.")

    async def prepare_practice_group_embeddings(self, practice_groups: List[Dict[str, str]]):
        """
        Precompute embeddings for each practice group.
        Expects a list of dicts with keys: ["name", "description"].
        """
        self._practice_groups = practice_groups
        group_texts = []
        for pg in self._practice_groups:
            # E.g. "Facilities and Business: Focuses on public agency business..."
            text_for_embedding = f"{pg['name']}: {pg['description']}"
            group_texts.append(text_for_embedding)

        embeddings = await get_embeddings_for_list(group_texts, model=self.model)
        for pg, emb in zip(self._practice_groups, embeddings):
            self._practice_group_embeddings[pg["name"]] = emb
        self.logger.info("Practice group embeddings prepared.")

    async def match_digest_sections(
        self,
        skeleton: Dict[str, Any],
        progress_handler=None
    ) -> Dict[str, Any]:
        """
        Match bill sections to each digest item purely using embeddings + cosine similarity.

        Skeleton structure is expected to have:
            skeleton["changes"] -> list of digest items
            skeleton["bill_sections"] -> list of bill sections, each with 'number' & 'text'

        We'll embed each digest item and each bill section, compute pairwise similarity,
        and assign sections to the digest item(s) that exceed a threshold.
        """

        # 1. Gather all digest texts
        digest_texts = []
        for change in skeleton["changes"]:
            # Combine existing_law + proposed_change for the embedding
            digest_body = f"{change.get('digest_text', '')}\n{change.get('existing_law', '')}\n{change.get('proposed_change', '')}"
            digest_texts.append(digest_body)

        # 2. Gather all bill section texts
        section_texts = []
        for sec in skeleton.get("bill_sections", []):
            section_texts.append(sec.get("text", ""))

        total_digests = len(digest_texts)
        total_sections = len(section_texts)

        # 3. Embed all digest items, embed all bill sections
        if progress_handler:
            progress_handler.update_progress(4, "Embedding digest items and bill sections")

        digest_embeddings, section_embeddings = await asyncio.gather(
            get_embeddings_for_list(digest_texts, model=self.model),
            get_embeddings_for_list(section_texts, model=self.model)
        )

        # 4. For each digest, find all sections above similarity threshold
        for dig_idx, change in enumerate(skeleton["changes"]):
            emb_dig = digest_embeddings[dig_idx]
            matched_sections = []
            for sec_idx, section in enumerate(skeleton.get("bill_sections", [])):
                emb_sec = section_embeddings[sec_idx]
                sim = cosine_similarity(emb_dig, emb_sec)
                if sim >= self.similarity_threshold:
                    matched_sections.append(section["number"])
            # Store them
            change["bill_sections"] = matched_sections

        if progress_handler:
            progress_handler.update_progress(4, "Completed embeddings-based section matching")

        return skeleton

    async def assign_practice_groups(
        self,
        skeleton: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Assign relevant practice groups to each legislative change by computing
        similarity of the change text with each practice group's embedded text.
        We'll pick one primary group (highest similarity) if above threshold,
        and optionally one or more secondary groups also above threshold * 0.9, etc.
        """

        if not self._practice_groups:
            self.logger.warning("No practice groups loaded. Please call prepare_practice_group_embeddings first.")
            return skeleton

        # We'll create a text for each change to embed
        changes_texts = []
        for change in skeleton["changes"]:
            combined_text = f"{change.get('digest_text','')} {change.get('existing_law','')} {change.get('proposed_change','')}"
            changes_texts.append(combined_text)

        change_embeddings = await get_embeddings_for_list(changes_texts, model=self.model)

        # For quick reference, store practice group name -> embedding
        practice_group_map = {pg["name"]: pg for pg in self._practice_groups}

        group_names = list(self._practice_group_embeddings.keys())
        group_embs = [self._practice_group_embeddings[g] for g in group_names]

        for i, change in enumerate(skeleton["changes"]):
            c_emb = change_embeddings[i]
            # Compare to each group embedding
            best_group = None
            best_sim = 0.0
            sims = []
            for gname, gemb in zip(group_names, group_embs):
                sim = cosine_similarity(c_emb, gemb)
                sims.append((gname, sim))
                if sim > best_sim:
                    best_sim = sim
                    best_group = gname

            # Build the final list of relevant groups
            # We'll pick the best group as primary if above threshold
            # Then any other group with sim >= 0.8 * best_sim as secondary (and also above threshold).
            final_groups = []
            if best_group and best_sim >= self.practice_group_threshold:
                final_groups.append({
                    "name": best_group,
                    "relevance": "primary",
                    "justification": f"Similarity score = {best_sim:.3f}"
                })

            # Check if any other group also is above threshold
            # and at least 80% of the best group's similarity
            for (gname, sim) in sims:
                if gname == best_group:
                    continue
                if sim >= self.practice_group_threshold and sim >= 0.8 * best_sim:
                    final_groups.append({
                        "name": gname,
                        "relevance": "secondary",
                        "justification": f"Similarity score = {sim:.3f}"
                    })

            # Sort by descending similarity
            final_groups.sort(key=lambda x: float(x["justification"].split("=")[1]), reverse=True)

            # Attach to skeleton
            change["practice_groups"] = final_groups

        return skeleton

    async def identify_local_agency_types(
        self,
        skeleton: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Determine if a local public agency is impacted by each legislative change,
        by comparing the change text to known local agency types.

        If the best match is below local_agency_threshold, we treat it as "No local public agency impacted."
        Otherwise, we store the best match as change["local_agency_type"].

        We'll embed each change, compare to each agency type embedding.
        """

        # Make sure local agency embeddings are ready
        await self.prepare_agency_type_embeddings()

        # We'll create a text for each change to embed
        changes_texts = []
        for change in skeleton["changes"]:
            combined_text = f"{change.get('digest_text','')} {change.get('existing_law','')} {change.get('proposed_change','')}"
            changes_texts.append(combined_text)

        change_embeddings = await get_embeddings_for_list(changes_texts, model=self.model)

        # For quick reference
        agency_types = list(self._local_agency_embeddings.keys())
        agency_embs = [self._local_agency_embeddings[a] for a in agency_types]

        for i, change in enumerate(skeleton["changes"]):
            c_emb = change_embeddings[i]

            best_agency = None
            best_sim = 0.0
            for a_type, a_emb in zip(agency_types, agency_embs):
                sim = cosine_similarity(c_emb, a_emb)
                if sim > best_sim:
                    best_sim = sim
                    best_agency = a_type

            if best_sim >= self.local_agency_threshold:
                change["local_agency_type"] = best_agency
                change["local_agency_confidence"] = best_sim
            else:
                change["local_agency_type"] = None
                change["local_agency_confidence"] = best_sim

        return skeleton
