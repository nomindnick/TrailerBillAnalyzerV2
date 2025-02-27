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
                margin: 0.75in;
                size: letter;
                @top-right {
                    content: "Page " counter(page) " of " counter(pages);
                    font-size: 9pt;
                    font-family: 'Helvetica Neue', Arial, sans-serif;
                    color: #666;
                }
                @bottom-left {
                    content: "TrailerBillAnalyzer Report";
                    font-size: 9pt;
                    font-family: 'Helvetica Neue', Arial, sans-serif;
                    color: #666;
                }
                @bottom-right {
                    content: "Generated: " attr(data-date);
                    font-size: 9pt;
                    font-family: 'Helvetica Neue', Arial, sans-serif;
                    color: #666;
                }
            }

            body {
                font-family: 'Helvetica Neue', Arial, sans-serif;
                line-height: 1.4;
                color: #333;
                max-width: 1000px;
                margin: 0 auto;
                padding: 0;
                font-size: 10pt;
            }

            /* Report Header Section */
            .report-header {
                background-color: #f6f9fc;
                padding: 1.2rem;
                border-radius: 4px;
                margin-bottom: 1.5rem;
                border: 1px solid #e1e7ef;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }

            .report-header h1 {
                color: #1a5f7a;
                margin: 0 0 0.5rem 0;
                padding-bottom: 0.5rem;
                font-size: 20pt;
                border-bottom: 2px solid #1a5f7a;
            }

            .report-header p {
                margin: 0.2rem 0;
                font-size: 10pt;
            }

            /* Executive Summary Section */
            .executive-summary {
                background-color: #f8fafc;
                padding: 1.2rem;
                border: 1px solid #e1e7ef;
                border-radius: 4px;
                margin-bottom: 1.5rem;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }

            .executive-summary h2 {
                color: #2c3e50;
                margin-top: 0;
                font-size: 14pt;
                border-bottom: 1px solid #e1e7ef;
                padding-bottom: 0.4rem;
            }

            /* Change Boxes */
            .change-box {
                background-color: #fff;
                border: 1px solid #e1e7ef;
                border-radius: 4px;
                margin-bottom: 1.5rem;
                padding: 0;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                page-break-inside: avoid;
            }

            .change-header {
                background-color: #1a5f7a;
                color: #fff;
                padding: 0.8rem;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-weight: bold;
                font-size: 11pt;
                display: flex;
                justify-content: space-between;
            }

            .change-content {
                padding: 1rem;
            }

            /* Section References */
            .section-list {
                margin-bottom: 1rem;
                font-size: 9pt;
                padding: 0.6rem;
                background-color: #f8f9fa;
                border-radius: 3px;
                border-left: 3px solid #1a5f7a;
            }

            .section-reference {
                display: inline-block;
                background-color: #e9f0f6;
                padding: 0.2rem 0.4rem;
                border-radius: 3px;
                margin-right: 0.25rem;
                margin-bottom: 0.25rem;
                border: 1px solid #d1dde6;
                font-size: 9pt;
                font-family: 'Courier New', monospace;
            }

            /* Content sections */
            .section-item {
                background-color: #f8f9fa;
                display: block;
                margin: 8px 0;
                padding: 8px;
                border-radius: 3px;
                border-left: 3px solid #1a5f7a;
                font-size: 9pt;
            }

            /* Action Items */
            .action-items {
                background-color: #f8f9fa;
                padding: 0.7rem;
                margin-top: 0.8rem;
                border-radius: 4px;
                border-left: 3px solid #e67e22;
            }

            .action-items strong {
                color: #e67e22;
                display: block;
                margin-bottom: 0.4rem;
                font-size: 10pt;
            }

            .action-items ul {
                margin: 0.4rem 0;
                padding-left: 1.2rem;
                font-size: 9pt;
            }

            /* Headings */
            h2, h3, h4 {
                break-after: avoid;
                color: #2c3e50;
            }

            h4 {
                font-size: 11pt;
                margin: 1rem 0 0.4rem 0;
                color: #1a5f7a;
            }

            /* Section titles */
            .report-section-title {
                margin-top: 1.8rem;
                border-bottom: 2px solid #1a5f7a;
                padding-bottom: 0.4rem;
                color: #2c3e50;
                font-size: 14pt;
                page-break-after: avoid;
            }

            /* Bill Text Section */
            .full-bill-text {
                margin-top: 1.2rem;
                padding-top: 1.2rem;
                border-top: 1px dashed #ccc;
            }

            .full-bill-text h4 {
                color: #1a5f7a;
                margin-top: 0;
                margin-bottom: 0.6rem;
                font-size: 11pt;
            }

            /* Paragraphs */
            p {
                margin: 0.5rem 0;
                font-size: 10pt;
            }

            ul, ol {
                margin: 0.5rem 0;
                padding-left: 1.2rem;
            }

            li {
                margin-bottom: 0.25rem;
            }

            strong {
                color: #2c3e50;
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
        from datetime import datetime
        
        total_changes = len(analyzed_data.get("changes", []))
        local_summary = f"{analyzed_data['metadata'].get('impacting_changes_count', 0)} changes potentially impact local agencies."

        template_data = {
            "bill_info": bill_info,
            "date_approved": bill_info.get("date_approved", "Not Available"),
            "total_changes": total_changes,
            "local_summary": local_summary,
            "state_summary": "N/A",
            "practice_areas": analyzed_data["metadata"].get("practice_groups_affected", []),
            "report_sections": sections,
            "now": datetime.now().strftime("%B %d, %Y")
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