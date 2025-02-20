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
    section_type: str  # 'local', 'state', or 'no_impact'

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
            # We'll create a structured breakdown:
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
        We’ll group changes into 3 main categories:
          1. Local Agency Impacts
          2. State Agency Impacts
          3. No Impact
        Each group is represented as a ReportSection object.
        """

        local_changes = []
        state_changes = []
        no_impact_changes = []

        for ch in analyzed_data.get("changes", []):
            # If it has local AND state, we can put it in both categories; 
            # but let's choose local if it's local; otherwise state if it's state
            # If neither, no_impact
            if ch.get("impacts_local_agencies"):
                local_changes.append(ch)
            elif ch.get("impacts_state_agencies"):
                state_changes.append(ch)
            else:
                no_impact_changes.append(ch)

        sections = []
        if local_changes:
            sections.append(ReportSection(
                title="Local Agency Impact",
                content={"changes": local_changes},
                section_type="local"
            ))
        if state_changes:
            sections.append(ReportSection(
                title="State Agency Impact",
                content={"changes": state_changes},
                section_type="state"
            ))
        if no_impact_changes:
            sections.append(ReportSection(
                title="Changes with No Local/State Agency Impact",
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
        local_count = analyzed_data["metadata"].get("local_impacts_count", 0)
        state_count = analyzed_data["metadata"].get("state_impacts_count", 0)

        # Just pick out practice groups that appear with "primary" relevance
        # in any of the changes. For illustration, we’ll keep it simple:
        practice_areas = set()
        for change in analyzed_data.get("changes", []):
            for pg in change.get("practice_groups", []):
                if pg.get("relevance") == "primary":
                    practice_areas.add(pg["name"])

        # Let's create a short summary text for the Executive Summary
        # that is more descriptive:
        local_summary = f"{local_count} changes potentially impact local agencies."
        state_summary = f"{state_count} changes potentially impact state agencies."

        # If we want to highlight a few big bullet points, we can do so here.
        # We'll keep it short for demonstration.
        summary_notes = []
        if local_count > 0:
            summary_notes.append(
                "Some changes provide funding opportunities or impose new compliance steps on cities, counties, or special districts."
            )
        if state_count > 0:
            summary_notes.append(
                "Certain provisions primarily affect state-level entities like Caltrans, DMV, or the High-Speed Rail Authority."
            )
        if not summary_notes:
            summary_notes.append("No direct impacts on local or state agencies identified.")

        summary_text = " ".join(summary_notes)

        template_data = {
            "bill_info": bill_info,
            "date_approved": bill_info.get("date_approved", "Not Available"),
            "total_changes": total_changes,
            "local_summary": local_summary,
            "state_summary": state_summary,
            "practice_areas": list(practice_areas),
            "report_sections": sections,
            "summary_text": summary_text
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
