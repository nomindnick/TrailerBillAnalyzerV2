import os
import logging
from typing import Dict, Any, List, Union
from jinja2 import Environment, FileSystemLoader
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
                font-family: 'Helvetica Neue', Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 1000px;
                margin: 0 auto;
                padding: 2rem;
            }

            .report-header {
                background-color: #f0f4f8;
                padding: 1.5rem;
                border-radius: 5px;
                margin-bottom: 2rem;
                border: 1px solid #dee2e6;
            }

            .report-header h1 {
                color: #1a5f7a;
                margin: 0 0 0.5rem 0;
                padding-bottom: 0.5rem;
            }

            .report-header p {
                margin: 0.2rem 0;
            }

            .executive-summary {
                background-color: #fafafa;
                padding: 1.5rem;
                border: 1px solid #ccc;
                border-radius: 5px;
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
                font-weight: bold;
            }

            .section-list {
                margin-bottom: 1rem;
                font-size: 0.9rem;
            }

            .section-reference {
                display: inline-block;
                background-color: #f0f4f8;
                padding: 0.25rem 0.5rem;
                border-radius: 3px;
                margin-right: 0.25rem;
                margin-bottom: 0.25rem;
                border: 1px solid #dee2e6;
            }

            .section-item {
                background-color: #f8f9fa;
                display: block;
                margin: 5px 0;
                padding: 6px;
                border-radius: 3px;
                border-left: 3px solid #1a5f7a;
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
                color: #444;
            }

            .full-bill-text {
                margin-top: 1.5rem;
                padding-top: 1.5rem;
                border-top: 1px dashed #ccc;
            }

            .full-bill-text h4 {
                color: #1a5f7a;
                margin-top: 0;
                margin-bottom: 0.75rem;
            }
        """

    def generate_report(
        self,
        analyzed_data: Dict[str, Any],
        bill_info: Dict[str, Any],
        parsed_bill: str,
        output_format: str = "html"
    ) -> Union[str, bytes]:
        try:
            sections = self._organize_report_sections(analyzed_data)
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
        analyzed_data: Dict[str, Any]
    ) -> List[ReportSection]:
        practice_group_map = defaultdict(list)
        no_local_impact_changes = []

        changes = analyzed_data.get("changes", [])

        for ch in changes:
            if not ch.get("impacts_local_agencies", False):
                no_local_impact_changes.append(ch)
                continue

            pgs = ch.get("practice_groups", [])
            primary_pg = None
            for pg in pgs:
                if pg.get("relevance") == "primary":
                    primary_pg = pg["name"]
                    break

            if not primary_pg:
                practice_group_map["(No Practice Group Specified)"].append(ch)
            else:
                practice_group_map[primary_pg].append(ch)

        sections = []
        for pg_name, changes_list in practice_group_map.items():
            sections.append(ReportSection(
                title=f"{pg_name} Practice Group",
                content={"changes": changes_list},
                section_type="practice_group"
            ))

        if no_local_impact_changes:
            sections.append(ReportSection(
                title="No Local Agency Impacts",
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
        total_changes = len(analyzed_data.get("changes", []))
        local_summary = f"{analyzed_data['metadata'].get('impacting_changes_count', 0)} changes potentially impact local agencies."

        template_data = {
            "bill_info": bill_info,
            "date_approved": bill_info.get("date_approved", "Not Available"),
            "total_changes": total_changes,
            "local_summary": local_summary,
            "state_summary": "N/A",
            "practice_areas": analyzed_data["metadata"].get("practice_groups_affected", []),
            "report_sections": sections
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