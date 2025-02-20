from typing import Dict, Any, List, Union, Optional
import logging
from jinja2 import Environment, FileSystemLoader
import os
from weasyprint import HTML, CSS
from dataclasses import dataclass, field
from collections import defaultdict

@dataclass
class ReportSection:
    title: str
    content: Dict[str, Any]
    section_type: str  # 'impact' or 'no_impact'
    practice_group: Optional[str] = None

class ReportGenerator:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        template_dir = os.path.join(os.path.dirname(__file__), 'templates')
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True
        )

        self._register_custom_filters()

        self.css_styles = """
            @page {
                margin: 1in;
                @top-right {
                    content: "Page " counter(page) " of " counter(pages);
                }
            }

            body {
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 1100px;
                margin: 0 auto;
                padding: 2rem;
            }

            .report-header {
                background-color: #f8f9fa;
                padding: 1.5rem;
                border-radius: 5px;
                margin-bottom: 2rem;
            }

            .report-header h1 {
                color: #1a5f7a;
                margin: 0 0 1rem 0;
                border-bottom: 2px solid #1a5f7a;
                padding-bottom: 0.5rem;
            }

            .executive-summary {
                background-color: #f1f7fa;
                padding: 1.5rem;
                border-radius: 5px;
                border: 1px solid #dee2e6;
                margin-bottom: 2rem;
            }

            .practice-group-section {
                margin-bottom: 2rem;
            }

            .change-box {
                background-color: #fff;
                border: 1px solid #dee2e6;
                border-radius: 5px;
                margin-bottom: 1.5rem;
                padding: 1rem;
            }

            .change-header {
                background-color: #1a5f7a;
                color: #fff;
                margin: -1rem -1rem 1rem -1rem;
                padding: 1rem;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }

            .section-list {
                margin-bottom: 1rem;
                font-size: 0.9rem;
            }

            .section-item {
                background-color: #f8f9fa;
                display: inline-block;
                margin-right: 5px;
                padding: 4px 6px;
                border-radius: 3px;
                margin-bottom: 5px;
            }

            .agency-list {
                margin: 0.5rem 0;
                padding-left: 1.2rem;
            }

            .agency-list li {
                list-style: disc;
            }

            .action-items {
                background-color: #f8f9fa;
                padding: 0.8rem;
                margin-top: 1rem;
                border-radius: 4px;
            }

            .action-items ul {
                margin: 0.5rem 0;
                padding-left: 1.2rem;
            }

            .no-impact-section {
                margin-top: 3rem;
                padding-top: 1rem;
                border-top: 2px solid #dee2e6;
            }

            h2, h3 {
                break-after: avoid;
            }
        """

    def generate_report(
        self,
        analyzed_data: Dict[str, Any],
        bill_info: Dict[str, Any],
        parsed_bill: Dict[str, Any],
        output_format: str = "html"
    ) -> Union[str, bytes]:

        try:
            report_sections = self._organize_report_sections(analyzed_data, parsed_bill)
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
    ) -> List[ReportSection]:
        sections = []
        changes = analyzed_data.get("changes", [])

        # Group changes that DO impact agencies by their primary practice groups
        practice_group_changes = self._group_by_practice_group(changes, parsed_bill)

        for group, group_changes in practice_group_changes.items():
            content = {"changes": group_changes}
            sections.append(ReportSection(
                title=group,
                content=content,
                section_type="impact",
                practice_group=group
            ))

        # general local agency
        general_impacts = self._get_general_impacts(changes, parsed_bill)
        if general_impacts:
            sections.append(ReportSection(
                title="General Local Agency Impact",
                content={"changes": general_impacts},
                section_type="impact",
                practice_group=None
            ))

        # no impact changes
        no_impact_changes = self._get_no_impact_changes(changes, parsed_bill)
        if no_impact_changes:
            sections.append(ReportSection(
                title="Changes with No Local Agency Impact",
                content={"changes": no_impact_changes},
                section_type="no_impact"
            ))

        return sections

    def _prepare_template_data(
        self,
        analyzed_data: Dict[str, Any],
        bill_info: Dict[str, Any],
        sections: List[ReportSection]
    ) -> Dict[str, Any]:
        total_changes = len(analyzed_data.get("changes", []))
        impacting = [c for c in analyzed_data.get("changes", []) if c.get("impacts_local_agencies")]
        impacting_count = len(impacting)

        practice_areas = set()
        for c in impacting:
            for pg in c.get("practice_groups", []):
                if pg.get("relevance") == "primary":
                    practice_areas.add(pg["name"])

        grouped_changes = {}
        general_local_agency_impact_changes = []
        no_impact_changes = []

        for section in sections:
            if section.section_type == "impact" and section.practice_group is not None:
                grouped_changes.setdefault(section.title, []).extend(section.content["changes"])
            elif section.section_type == "impact" and section.practice_group is None:
                general_local_agency_impact_changes.extend(section.content["changes"])
            elif section.section_type == "no_impact":
                no_impact_changes.extend(section.content["changes"])

        template_data = {
            "bill_info": bill_info,
            "date_approved": bill_info["date_approved"] if bill_info.get("date_approved") else "Not Available",
            "total_changes": total_changes,
            "impacting_changes": impacting_count,
            "practice_areas": list(practice_areas),
            "grouped_changes": grouped_changes,
            "general_local_agency_impact_changes": general_local_agency_impact_changes,
            "no_impact_changes": no_impact_changes,
            "sections": sections
        }

        return template_data

    def _group_by_practice_group(
        self,
        changes: List[Dict[str, Any]],
        parsed_bill: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        grouped = {}
        for ch in changes:
            if ch.get("impacts_local_agencies"):
                primary_groups = [
                    gp["name"] for gp in ch.get("practice_groups", [])
                    if gp.get("relevance") == "primary"
                ]
                if primary_groups:
                    for pg in primary_groups:
                        grouped.setdefault(pg, []).append(
                            self._process_single_change(ch, parsed_bill)
                        )
        return grouped

    def _get_general_impacts(
        self,
        changes: List[Dict[str, Any]],
        parsed_bill: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        results = []
        for ch in changes:
            if ch.get("impacts_local_agencies"):
                primary_groups = [
                    gp for gp in ch.get("practice_groups", [])
                    if gp.get("relevance") == "primary"
                ]
                if not primary_groups:
                    results.append(self._process_single_change(ch, parsed_bill))
        return results

    def _get_no_impact_changes(
        self,
        changes: List[Dict[str, Any]],
        parsed_bill: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        results = []
        for ch in changes:
            if not ch.get("impacts_local_agencies", False):
                results.append(self._process_single_change(ch, parsed_bill))
        return results

    def _process_single_change(
        self, change: Dict[str, Any], parsed_bill: Dict[str, Any]
    ) -> Dict[str, Any]:
        processed_change = {
            "id": change.get("id"),
            "substantive_change": change.get("substantive_change", ""),
            "local_agency_impact": change.get("local_agency_impact", ""),
            "impacts_local_agencies": change.get("impacts_local_agencies", False),
            "practice_groups": change.get("practice_groups", []),
            "key_action_items": change.get("key_action_items", []),
            "deadlines": change.get("deadlines", []),
            "requirements": change.get("requirements", []),
            "existing_law": change.get("existing_law", ""),
            "proposed_change": change.get("proposed_change", ""),
            "section_details": []
        }

        # We do want the 'existing_law' and 'proposed_change' from skeleton if present:
        # The skeleton's structure stores them in each change as well.

        bill_sections_dict = parsed_bill.get("bill_sections", {})
        matched_sections = change.get("bill_sections", [])
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

    def _register_custom_filters(self) -> None:
        self.jinja_env.filters.update({
            "format_analysis": self._format_analysis
        })

    def _format_analysis(self, text: str) -> str:
        return text

    def _generate_html_report(self, template_data: Dict[str, Any]) -> str:
        try:
            template = self.jinja_env.get_template('report.html')
            return template.render(**template_data)
        except Exception as e:
            self.logger.error(f"Error generating HTML report: {str(e)}")
            raise

    def _convert_to_pdf(self, html_content: str) -> bytes:
        try:
            css = CSS(string=self.css_styles)
            html = HTML(string=html_content)
            return html.write_pdf(stylesheets=[css])
        except Exception as e:
            self.logger.error(f"Error converting to PDF: {str(e)}")
            raise

    def save_report(self, report_content: Union[str, bytes], filename: str) -> None:
        try:
            mode = 'wb' if isinstance(report_content, bytes) else 'w'
            with open(filename, mode, encoding='utf-8' if mode == 'w' else None) as f:
                f.write(report_content)
        except Exception as e:
            self.logger.error(f"Error saving report: {str(e)}")
            raise
