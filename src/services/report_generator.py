from typing import Dict, Any, List, Union, Optional
import logging
from jinja2 import Environment, FileSystemLoader
import os
from weasyprint import HTML, CSS
from dataclasses import dataclass
from collections import defaultdict

@dataclass
class ReportSection:
    title: str
    content: Dict[str, Any]
    section_type: str  # e.g. 'practice_group' or 'no_impact'

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

            h2, h3 {
                break-after: avoid;
            }

            .report-section-title {
                margin-top: 2rem;
                border-bottom: 2px solid #dee2e6;
                padding-bottom: 0.5rem;
            }

            .key-topics-list {
                margin: 0.5rem 0 0.5rem 1.2rem;
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
        Generates either HTML or PDF based on the analyzed data.
        """

        try:
            sections = self._organize_report_sections(analyzed_data, parsed_bill)
            template_data = self._prepare_template_data(analyzed_data, bill_info, sections)

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
        """
        Group changes by their *primary* practice group. Then gather any changes
        that have no local agency impacts or no practice group into a separate
        "No Direct Local Agency Impact" section.
        """
        practice_group_map = defaultdict(list)
        no_local_impact_changes = []

        changes = analyzed_data.get("changes", [])

        for ch in changes:
            # If it doesn't impact local agencies at all, or if it has
            # no recognized practice group, treat it as "No Direct Local Agency Impact".
            if not ch.get("impacts_local_agencies", False):
                no_local_impact_changes.append(ch)
                continue

            # Look for the "primary" practice group in ch["practice_groups"].
            pgs = ch.get("practice_groups", [])
            primary_pg = None
            for pg in pgs:
                if pg.get("relevance") == "primary":
                    primary_pg = pg["name"]
                    break

            if not primary_pg:
                # if no primary group is assigned, treat it as no local impact for grouping
                no_local_impact_changes.append(ch)
            else:
                practice_group_map[primary_pg].append(ch)

        sections = []
        # Create a section for each practice group that has changes
        for pg_name, changes_list in practice_group_map.items():
            sections.append(ReportSection(
                title=f"{pg_name} Practice Group",
                content={"changes": changes_list},
                section_type="practice_group"
            ))

        # Finally, add a "No Direct Local Agency Impact" section if any
        if no_local_impact_changes:
            sections.append(ReportSection(
                title="No Direct Local Agency Impact",
                content={"changes": no_local_impact_changes},
                section_type="no_impact"
            ))

        return sections

    def _prepare_template_data(
        self,
        analyzed_data: Dict[str, Any],
        bill_info: Dict[str, Any],
        sections: List[ReportSection]
    ) -> Dict[str, Any]:

        # Summaries for local and state
        total_changes = len(analyzed_data.get("changes", []))
        local_count = analyzed_data["metadata"].get("local_impacts_count", 0)
        state_count = analyzed_data["metadata"].get("state_impacts_count", 0)

        # Gather short bullet items from each change's "substantive_change" as key topics
        key_topics = []
        for ch in analyzed_data.get("changes", []):
            # We'll just take the first sentence or so
            summ = ch.get("substantive_change", "")
            if summ:
                # Grab up to 150 chars
                short_summ = (summ[:150] + '...') if len(summ) > 150 else summ
                key_topics.append(short_summ.strip())

        # Just pick out practice groups that appear as 'primary' in any of the changes
        practice_areas = set()
        for change in analyzed_data.get("changes", []):
            for pg in change.get("practice_groups", []):
                if pg.get("relevance") == "primary":
                    practice_areas.add(pg["name"])

        # Build a short bullet-list of unique topics (limit to 6 for brevity)
        unique_topics = list(dict.fromkeys(key_topics))  # preserve insertion order & remove dups
        short_topic_list = unique_topics[:6]

        # Executive summary text
        local_summary = f"{local_count} changes potentially impact local agencies."
        state_summary = f"{state_count} changes potentially impact state agencies."
        if local_count == 0 and state_count == 0:
            summary_text = "No direct local or state agency impacts identified."
        else:
            summary_text = (
                "Key funding, compliance, and operational changes may affect agencies at multiple levels."
            )

        template_data = {
            "bill_info": bill_info,
            "date_approved": bill_info.get("date_approved", "Not Available"),
            "total_changes": total_changes,
            "local_summary": local_summary,
            "state_summary": state_summary,
            "practice_areas": list(practice_areas),
            "report_sections": sections,
            "summary_text": summary_text,
            "key_topics": short_topic_list
        }
        return template_data

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

    def _register_custom_filters(self) -> None:
        self.jinja_env.filters.update({
            "format_analysis": self._format_analysis
        })

    def _format_analysis(self, text: str) -> str:
        return text
