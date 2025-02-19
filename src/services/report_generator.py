from typing import Dict, Any, List, Union, Optional
from datetime import datetime
import logging
from jinja2 import Environment, FileSystemLoader
import os
from weasyprint import HTML, CSS
from dataclasses import dataclass, field
from collections import defaultdict

@dataclass
class ReportSection:
    """Represents a section in the report"""
    title: str
    content: Dict[str, Any]
    section_type: str  # 'impact' or 'no_impact'
    practice_group: Optional[str] = None

class ReportGenerator:
    """Enhanced report generator with improved section organization and formatting"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Initialize Jinja environment
        template_dir = os.path.join(os.path.dirname(__file__), 'templates')
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True
        )

        # Register custom filters
        self._register_custom_filters()

        # You can store common CSS for PDF conversion here if you like
        self.css_styles = """
            @page {
                margin: 1in;
                @top-right {
                    content: "Page " counter(page) " of " counter(pages);
                }
            }

            /* Enhanced table styling */
            table {
                width: 100%;
                border-collapse: collapse;
                margin: 1em 0;
            }

            th, td {
                border: 1px solid #dee2e6;
                padding: 0.5rem;
            }

            th {
                background-color: #f8f9fa;
            }

            /* Improved section spacing */
            section {
                margin-bottom: 2em;
                break-inside: avoid;
            }

            h1, h2, h3 {
                break-after: avoid;
            }

            /* Better list formatting */
            ul, ol {
                margin: 0.5em 0;
                padding-left: 1.5em;
            }

            li {
                margin-bottom: 0.25em;
            }

            /* Deadline table specific styling */
            .deadline-table th {
                background-color: #e9ecef;
                font-weight: bold;
            }
        """

    def generate_report(
        self,
        analyzed_data: Dict[str, Any],
        bill_info: Dict[str, Any],
        parsed_bill: Dict[str, Any],
        output_format: str = "html"
    ) -> Union[str, bytes]:
        """
        Generate the report. `parsed_bill` is expected to be a dict with
        a "bill_sections" key. The `analyzed_data` structure is the final
        AI-enhanced analysis, containing a "changes" list. Each change 
        has "bill_sections" which is a list of dicts such as:
            [
              {
                "section_id": "1",
                "confidence": 0.9,
                "match_type": "code_ref"
              },
              ...
            ]
        """
        try:
            # Create structured sections for the final report
            report_sections = self._organize_report_sections(analyzed_data, parsed_bill)

            # Prepare additional data for Jinja template
            template_data = self._prepare_template_data(analyzed_data, bill_info, report_sections)

            if output_format == "html":
                return self._generate_html_report(template_data)
            elif output_format == "pdf":
                html_content = self._generate_html_report(template_data)
                return self._convert_to_pdf(html_content)
            else:
                raise ValueError(f"Unsupported output format: {output_format}")
        except Exception as e:
            self.logger.error(f"Error generating report: {str(e)}")
            raise

    def _organize_report_sections(
        self,
        analyzed_data: Dict[str, Any],
        parsed_bill: Dict[str, Any]
    ) -> List['ReportSection']:
        """
        Build a list of ReportSection objects. Each 'change' can be categorized by:
        - whether it has local agency impact
        - which practice group it affects (primary)

        Return a list of these sections for later use in the template data.
        """
        sections = []
        changes = analyzed_data.get("changes", [])

        # 1. Group changes that DO impact agencies by their primary practice groups
        practice_group_changes = self._group_by_practice_group(changes, parsed_bill)

        # Each practice group becomes one "ReportSection"
        for group, group_changes in practice_group_changes.items():
            content = {
                "changes": group_changes
            }
            sections.append(
                ReportSection(
                    title=group,
                    content=content,
                    section_type="impact",
                    practice_group=group
                )
            )

        # 2. A "general local agency impact" section for changes that have impact
        #    but no primary practice group
        general_impacts = self._get_general_impacts(changes, parsed_bill)
        if general_impacts:
            sections.append(
                ReportSection(
                    title="General Local Agency Impact",
                    content={"changes": general_impacts},
                    section_type="impact",
                    practice_group=None
                )
            )

        # 3. A "no local agency impact" section
        no_impact_changes = self._get_no_impact_changes(changes, parsed_bill)
        if no_impact_changes:
            sections.append(
                ReportSection(
                    title="Changes with No Local Agency Impact",
                    content={"changes": no_impact_changes},
                    section_type="no_impact"
                )
            )

        return sections

    def _process_single_change(
        self, change: Dict[str, Any], parsed_bill: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prepare a single 'change' dict for display, including
        looking up the bill section text, code modifications, etc.
        """
        processed_change = {
            "id": change.get("id"),
            "substantive_change": change.get("substantive_change", ""),
            "local_agency_impact": change.get("local_agency_impact", ""),
            "impacts_local_agencies": change.get("impacts_local_agencies", False),
            "practice_groups": change.get("practice_groups", []),
            "key_action_items": change.get("key_action_items", []),
            "deadlines": change.get("deadlines", []),
            "requirements": change.get("requirements", []),
            "section_details": [],
        }

        bill_sections_dict = parsed_bill.get("bill_sections", {})
        matched_sections = change.get("bill_sections", [])  # list of dicts
        for ms in matched_sections:
            sid = ms["section_id"]
            if sid in bill_sections_dict:
                sec_obj = bill_sections_dict[sid]
                section_details = {
                    "number": sid,
                    "text": sec_obj.get("text", ""),
                    "code_modifications": sec_obj.get("code_modifications", []),
                    "confidence": ms.get("confidence"),
                    "match_type": ms.get("match_type")
                }
                processed_change["section_details"].append(section_details)

        return processed_change

    def _group_by_practice_group(
        self, changes: List[Dict[str, Any]], parsed_bill: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Collect changes that have local agency impact under their 'primary' practice groups.
        Return a dict keyed by the practice group name -> list of changes.
        """
        grouped = {}
        for ch in changes:
            if ch.get("impacts_local_agencies"):
                # All groups with relevance == primary
                primary_groups = [
                    gp["name"] for gp in ch.get("practice_groups", [])
                    if gp.get("relevance") == "primary"
                ]
                # If multiple primary groups, add to each:
                for pg in primary_groups:
                    grouped.setdefault(pg, []).append(
                        self._process_single_change(ch, parsed_bill)
                    )
        return grouped

    def _get_general_impacts(
        self, changes: List[Dict[str, Any]], parsed_bill: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Return changes that do impact local agencies but have NO 'primary' practice group.
        """
        results = []
        for ch in changes:
            if ch.get("impacts_local_agencies"):
                # Check if there are *any* primary groups
                primary_groups = [
                    gp for gp in ch.get("practice_groups", [])
                    if gp.get("relevance") == "primary"
                ]
                if not primary_groups:
                    results.append(self._process_single_change(ch, parsed_bill))
        return results

    def _get_no_impact_changes(
        self, changes: List[Dict[str, Any]], parsed_bill: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Return changes that do NOT impact local agencies at all.
        """
        results = []
        for ch in changes:
            if not ch.get("impacts_local_agencies", False):
                results.append(self._process_single_change(ch, parsed_bill))
        return results

    def _prepare_template_data(
        self,
        analyzed_data: Dict[str, Any],
        bill_info: Dict[str, Any],
        sections: List[ReportSection]
    ) -> Dict[str, Any]:
        """
        Build the data structure sent to the Jinja template.
        The existing 'report.html' uses:
          - grouped_changes
          - general_local_agency_impact_changes
          - no_impact_changes

        Our new approach yields a list of ReportSection objects. We simply
        convert them back to these template-friendly structures.
        """
        total_changes = len(analyzed_data.get("changes", []))
        impacting = [c for c in analyzed_data.get("changes", []) if c.get("impacts_local_agencies")]
        impacting_count = len(impacting)

        # Collect a set of practice area names from all "primary" practice_groups
        practice_areas = set()
        for c in impacting:
            for pg in c.get("practice_groups", []):
                if pg.get("relevance") == "primary":
                    practice_areas.add(pg["name"])

        # Convert the list of `ReportSection` objects into the format
        # that the template expects: grouped_changes, general_local_agency_impact_changes, and no_impact_changes.
        grouped_changes = {}
        general_local_agency_impact_changes = []
        no_impact_changes = []

        for section in sections:
            # Each section.content["changes"] is a list of processed changes
            if section.section_type == "impact" and section.practice_group is not None:
                # store under grouped_changes
                grouped_changes.setdefault(section.title, []).extend(section.content["changes"])
            elif section.section_type == "impact" and section.practice_group is None:
                # these belong in the general local agency impact section
                general_local_agency_impact_changes.extend(section.content["changes"])
            elif section.section_type == "no_impact":
                no_impact_changes.extend(section.content["changes"])

        template_data = {
            "bill_info": bill_info,
            "date_approved": bill_info["date_approved"] if bill_info.get("date_approved") else "Not Available",
            "total_changes": total_changes,
            "impacting_changes": impacting_count,
            "practice_areas": list(practice_areas),
            # Old-style template data:
            "grouped_changes": grouped_changes,
            "general_local_agency_impact_changes": general_local_agency_impact_changes,
            "no_impact_changes": no_impact_changes,
            # We also keep the new sections if you need them in the future
            "sections": sections
        }
        return template_data

    def _register_custom_filters(self) -> None:
        """
        Register any custom Jinja2 filters you might need.
        """
        self.jinja_env.filters.update({
            "format_analysis": self._format_analysis
        })

    def _format_analysis(self, text: str) -> str:
        """
        Example of a custom filter that might format analysis text
        in a special way. Just returns text for now.
        """
        return text

    def _generate_html_report(self, template_data: Dict[str, Any]) -> str:
        """
        Render our `report.html` template into an HTML string
        using the data from `template_data`.
        """
        try:
            template = self.jinja_env.get_template('report.html')
            return template.render(**template_data)
        except Exception as e:
            self.logger.error(f"Error generating HTML report: {str(e)}")
            raise

    def _convert_to_pdf(self, html_content: str) -> bytes:
        """
        Convert the given HTML string into a PDF.
        """
        try:
            css = CSS(string=self.css_styles)
            html = HTML(string=html_content)
            return html.write_pdf(stylesheets=[css])
        except Exception as e:
            self.logger.error(f"Error converting to PDF: {str(e)}")
            raise

    def save_report(self, report_content: Union[str, bytes], filename: str) -> None:
        """
        Write the report_content to a file (HTML or PDF) on disk.
        """
        try:
            mode = 'wb' if isinstance(report_content, bytes) else 'w'
            with open(filename, mode, encoding='utf-8' if mode == 'w' else None) as f:
                f.write(report_content)
        except Exception as e:
            self.logger.error(f"Error saving report: {str(e)}")
            raise
