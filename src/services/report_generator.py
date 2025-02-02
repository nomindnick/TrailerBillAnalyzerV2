import logging
import re
from typing import Dict, Any, List, Union
from datetime import datetime
from weasyprint import HTML, CSS
from jinja2 import Environment, select_autoescape

class ReportGenerator:
    """
    Generates formatted reports from analyzed bill data.
    Can produce text, HTML, or PDF outputs.
    """

    def __init__(self):
        """Initialize the report generator with a logger and default CSS styles."""
        self.logger = logging.getLogger(__name__)
        self.css_styles = self._get_default_css()

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def generate_report(
        self,
        analyzed_skeleton: Dict[str, Any],
        bill_info: Dict[str, Any],
        output_format: str = "html"
    ) -> Union[str, bytes]:
        """
        Generate a report in the specified format.

        :param analyzed_skeleton: The analyzed bill data
        :param bill_info: Basic information about the bill
        :param output_format: "text", "html", or "pdf"
        :return: str for text/html formats, bytes for PDF format
        """
        try:
            if output_format == "text":
                return self._generate_text_report(analyzed_skeleton, bill_info)
            elif output_format == "html":
                return self._generate_html_report(analyzed_skeleton, bill_info)
            elif output_format == "pdf":
                html_content = self._generate_html_report(analyzed_skeleton, bill_info)
                return self._convert_to_pdf(html_content)
            else:
                raise ValueError(f"Unsupported output format: {output_format}")

        except Exception as exc:
            self.logger.error(f"Error generating {output_format} report: {str(exc)}")
            raise

    def save_report(self, report_content: Union[str, bytes], filename: str) -> None:
        """
        Save the report to a file.

        :param report_content: Content returned by generate_report
        :param filename: The file path where the report should be saved
        """
        mode = 'wb' if isinstance(report_content, bytes) else 'w'
        try:
            with open(filename, mode) as f:
                f.write(report_content)
        except Exception as exc:
            self.logger.error(f"Error saving report: {str(exc)}")
            raise

    # ----------------------------------------------------------------------
    # Text Report
    # ----------------------------------------------------------------------

    def _generate_text_report(self, analyzed_skeleton: Dict[str, Any], bill_info: Dict[str, Any]) -> str:
        """Generate a plain text version of the report."""
        try:
            parts = [
                self._generate_header_text(bill_info),
                self._generate_executive_summary_text(analyzed_skeleton),
                self._generate_practice_area_analysis_text(analyzed_skeleton)
            ]
            return "\n\n".join(parts)
        except Exception as exc:
            self.logger.error(f"Error generating text report: {str(exc)}")
            raise

    def _generate_header_text(self, bill_info: Dict[str, Any]) -> str:
        """Generate the text report header section."""
        try:
            date_approved = self._get_date_approved(bill_info)
            return (
                f"BILL ANALYSIS REPORT\n"
                f"{'-' * 50}\n"
                f"Bill Number: {bill_info.get('bill_number', 'Not Available')}\n"
                f"Chapter Number: {bill_info.get('chapter_number', 'Not Available')}\n"
                f"Title: {bill_info.get('title', 'Not Available')}\n"
                f"Date Approved: {date_approved}"
            )
        except Exception as exc:
            self.logger.error(f"Error generating header: {str(exc)}")
            return "BILL ANALYSIS REPORT\n" + ("-" * 50)

    def _generate_executive_summary_text(self, analyzed_skeleton: Dict[str, Any]) -> str:
        """Generate an executive summary section for the text report."""
        total_changes = len(analyzed_skeleton['changes'])
        impacting_changes = len(self._get_impacting_changes(analyzed_skeleton))
        practice_groups = ', '.join(analyzed_skeleton['metadata']['practice_groups_affected'])
        return (
            f"EXECUTIVE SUMMARY\n"
            f"{'-' * 50}\n"
            f"Total Changes: {total_changes}\n"
            f"Changes Impacting Local Agencies: {impacting_changes}\n"
            f"Practice Areas Affected: {practice_groups}"
        )

    def _generate_practice_area_analysis_text(self, analyzed_skeleton: Dict[str, Any]) -> str:
        """Generate the analysis-by-practice-area section for the text report."""
        sections = ["ANALYSIS BY PRACTICE AREA", "=" * 24]

        impacting_changes = self._get_impacting_changes(analyzed_skeleton)
        no_impact_changes = self._get_no_impact_changes(analyzed_skeleton)
        affected_areas = analyzed_skeleton['metadata']['practice_groups_affected']

        # For each practice area, add relevant changes
        for area in affected_areas:
            sections.append(self._generate_practice_area_section_text(area, impacting_changes))

        # If there are no-impact changes, add them at the end
        if no_impact_changes:
            sections.append(self._generate_no_impact_section_text(no_impact_changes))

        return "\n".join(sections)

    def _generate_practice_area_section_text(self, area: str, changes: List[Dict[str, Any]]) -> str:
        """Generate the text describing how a practice area is impacted by changes."""
        section_lines = [f"\n{area.upper()}", "=" * len(area)]

        for change in changes:
            # Only include changes relevant to this practice area
            if not any(pg['name'] == area for pg in change.get('practice_groups', [])):
                continue

            # Header lines
            section_lines.append(self._format_change_header(change))

            # Relevance level
            relevance = next(
                (pg['relevance'] for pg in change.get('practice_groups', []) if pg['name'] == area),
                'unknown'
            )
            section_lines.append(f"Relevance Level: {relevance.title()}")

            # Impact analysis
            if change.get('impact_analysis'):
                section_lines.append("\nImpact Analysis:")
                section_lines.append(self._format_analysis_section_text(change['impact_analysis']))

            section_lines.append("\n" + "-" * 80 + "\n")

        return "\n".join(section_lines)

    def _generate_no_impact_section_text(self, changes: List[Dict[str, Any]]) -> str:
        """Generate a text section for changes that have no local agency impact."""
        if not changes:
            return ""

        section_lines = ["\nCHANGES WITH NO LOCAL AGENCY IMPACT", "=" * 31]
        for change in changes:
            section_lines.append(self._format_change_header(change))
            section_lines.append("Summary:")
            digest_text = change.get('digest_text', '')
            section_lines.append(self._format_analysis_section_text(digest_text))
            section_lines.append("\n" + "-" * 80 + "\n")

        return "\n".join(section_lines)

    # ----------------------------------------------------------------------
    # HTML/PDF Report
    # ----------------------------------------------------------------------

    def _generate_html_report(self, analyzed_skeleton: Dict[str, Any], bill_info: Dict[str, Any]) -> str:
        """Generate the HTML version of the report."""
        try:
            # Prepare data for template
            date_approved = self._get_date_approved(bill_info)
            self._prepare_changes_for_template(analyzed_skeleton)

            # Jinja2 template
            html_template = self._get_html_template()
            template_data = {
                'css_styles': self.css_styles,
                'bill_info': bill_info,
                'date_approved': date_approved,
                'total_changes': len(analyzed_skeleton['changes']),
                'impacting_changes': len(self._get_impacting_changes(analyzed_skeleton)),
                'practice_areas': analyzed_skeleton['metadata']['practice_groups_affected'],
                'changes': self._get_impacting_changes(analyzed_skeleton),
                'no_impact_changes': self._get_no_impact_changes(analyzed_skeleton),
                'get_practice_group_relevance': self._generate_practice_group_relevance,
                'get_no_impact_summary': self._generate_no_impact_summary,
                'format_analysis_section_html': self._format_analysis_section_html
            }

            # Render template
            env = Environment(autoescape=select_autoescape(['html', 'xml']))
            template = env.from_string(html_template)
            return template.render(**template_data)

        except Exception as exc:
            self.logger.error(f"Error generating HTML report: {str(exc)}")
            raise

    def _convert_to_pdf(self, html_content: str) -> bytes:
        """
        Convert the HTML report to PDF using WeasyPrint.
        Returns the PDF as bytes.
        """
        try:
            html = HTML(string=html_content)
            stylesheet = CSS(string=self.css_styles)
            return html.write_pdf(stylesheets=[stylesheet])
        except Exception as exc:
            self.logger.error(f"Error converting to PDF: {str(exc)}")
            self.logger.exception("Full traceback:")
            raise

    # ----------------------------------------------------------------------
    # Formatting Helpers
    # ----------------------------------------------------------------------

    def _format_analysis_section_html(self, analysis_text: str) -> str:
        """Convert raw analysis text into formatted HTML."""
        if not analysis_text:
            return ""

        lines = self._extract_lines(analysis_text)
        return self._process_subheadings_and_bullets_html(lines)

    def _format_analysis_section_text(self, analysis_text: str) -> str:
        """Convert raw analysis text into formatted plaintext."""
        lines = self._extract_lines(analysis_text)
        return self._process_subheadings_and_bullets_text(lines)

    def _extract_lines(self, raw_text: str) -> List[str]:
        """Extract non-empty lines from text, stripping out XML/HTML tags."""
        if not raw_text:
            return []

        cleaned_text = re.sub(r'<[^>]+>', '', raw_text)
        return [line.strip() for line in cleaned_text.split('\n') if line.strip()]

    def _process_subheadings_and_bullets_html(self, lines: List[str]) -> str:
        """
        Convert lines into subheadings (h4) when a line ends with ':' 
        and bullet points (<ul><li>) otherwise.
        """
        html_chunks = []
        in_list = False

        for line in lines:
            if line.endswith(':'):
                if in_list:
                    html_chunks.append("</ul>")
                    in_list = False
                subheading = line[:-1]  # remove trailing colon
                html_chunks.append(f"<h4>{subheading}</h4>")
            else:
                if not in_list:
                    html_chunks.append("<ul>")
                    in_list = True
                html_chunks.append(f"<li>{line}</li>")

        if in_list:
            html_chunks.append("</ul>")

        return "\n".join(html_chunks)

    def _process_subheadings_and_bullets_text(self, lines: List[str]) -> str:
        """
        Convert lines into uppercase subheadings when a line ends with ':'
        and bullet points otherwise.
        """
        output_lines = []
        in_bullet_block = False

        for line in lines:
            if line.endswith(':'):
                # Close out any existing bullet block
                if in_bullet_block:
                    output_lines.append("")
                    in_bullet_block = False

                subheading_text = line[:-1].upper()
                output_lines.append(subheading_text)
                output_lines.append("-" * len(subheading_text))
            else:
                if not in_bullet_block:
                    in_bullet_block = True
                output_lines.append(f"  • {line}")

        return "\n".join(output_lines)

    # ----------------------------------------------------------------------
    # Practice Group Logic
    # ----------------------------------------------------------------------

    def _generate_practice_group_relevance(self, change: Dict[str, Any], practice_group: str) -> str:
        """
        Generate the textual explanation for how a change impacts a specific practice group.
        """
        pg_entry = next(
            (pg for pg in change.get("practice_groups", []) if pg["name"] == practice_group),
            None
        )
        if not pg_entry:
            return ""

        relevance_level = pg_entry.get("relevance", "")
        explanations = {
            "Business and Facilities": {
                "primary": (
                    "This change directly affects the business operations and facilities "
                    "management of local agencies (e.g., infrastructure, procurement, or operational requirements)."
                ),
                "secondary": (
                    "This change has indirect implications for local agency business operations "
                    "or facilities management (e.g., optional or procedural adjustments)."
                )
            },
            "Public Finance": {
                "primary": (
                    "This change has direct fiscal implications for local agencies, affecting "
                    "funding mechanisms, financial obligations, or budgeting."
                ),
                "secondary": (
                    "This change presents potential financial considerations for local agencies "
                    "through optional programs or indirect fiscal effects."
                )
            },
            # Add additional practice groups as needed
        }

        base_explanation = explanations.get(practice_group, {}).get(relevance_level, "")
        if not base_explanation:
            return ""

        return f"Practice Group Relevance ({relevance_level.title()}): {base_explanation}"

    def _generate_no_impact_summary(self, change: Dict[str, Any]) -> str:
        """
        Generate a message explaining why a change does not affect local agencies.
        """
        digest_text = change.get('digest_text', '')
        state_only_indicators = [
            "state agency", "state department", "state entity",
            "Department of ", "state vehicle fleet", "High-Speed Rail Authority"
        ]

        if any(ind.lower() in digest_text.lower() for ind in state_only_indicators):
            return (
                "This change affects only state-level agencies and operations, "
                "with no direct impact on local agencies."
            )

        if any(word in digest_text.lower() for word in ["technical", "administrative"]):
            return (
                "This is a technical or administrative change that does not affect "
                "local agency operations or requirements."
            )

        return (
            "This change does not create new requirements or modify existing obligations, "
            "and does not directly affect local agency operations."
        )

    # ----------------------------------------------------------------------
    # Internal Utilities
    # ----------------------------------------------------------------------

    def _get_date_approved(self, bill_info: Dict[str, Any]) -> str:
        """Safely return a date string or 'Not Available' if no date is provided."""
        date_approved = bill_info.get('date_approved')
        if isinstance(date_approved, datetime):
            return date_approved.strftime('%Y-%m-%d')
        return 'Not Available'

    def _format_change_header(self, change: Dict[str, Any]) -> str:
        """
        Format the text report header for a change, including bill section references.
        """
        refs = change.get('bill_sections', [])
        sections = f"[Bill Sections: {', '.join(refs)}]" if refs else ""
        return f"\n{sections}\n"

    def _get_impacting_changes(self, analyzed_skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return only the changes that impact local agencies."""
        return [chg for chg in analyzed_skeleton['changes'] if chg.get('impacts_local_agencies')]

    def _get_no_impact_changes(self, analyzed_skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return changes that do not impact local agencies."""
        return [chg for chg in analyzed_skeleton['changes'] if not chg.get('impacts_local_agencies')]

    def _prepare_changes_for_template(self, analyzed_skeleton: Dict[str, Any]) -> None:
        """
        Modify the analyzed skeleton in-place so each change has
        a list of 'practice_groups_names' for easier handling in the Jinja template.
        """
        for change in analyzed_skeleton['changes']:
            change['practice_groups_names'] = [
                pg['name'] for pg in change.get('practice_groups', [])
            ]

    # ----------------------------------------------------------------------
    # Templates / Default CSS
    # ----------------------------------------------------------------------

    def _get_html_template(self) -> str:
        """Return the Jinja2 template string for the HTML report."""
        return r"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Bill Analysis Report - {{ bill_info.bill_number }}</title>
            <style>
                {{ css_styles }}
            </style>
        </head>
        <body>
            <h1>Bill Analysis Report</h1>

            <div class="header-info">
                <p><strong>Bill Number:</strong> {{ bill_info.bill_number }}</p>
                <p><strong>Chapter Number:</strong> {{ bill_info.chapter_number }}</p>
                <p><strong>Title:</strong> {{ bill_info.title }}</p>
                <p><strong>Date Approved:</strong> {{ date_approved }}</p>
            </div>

            <div class="executive-summary">
                <h2>Executive Summary</h2>
                <p><strong>Total Changes:</strong> {{ total_changes }}</p>
                <p><strong>Changes Impacting Local Agencies:</strong> {{ impacting_changes }}</p>
                <p><strong>Practice Areas Affected:</strong> {{ practice_areas|join(', ') }}</p>
            </div>

            <h2>Analysis by Practice Area</h2>
            {% for area in practice_areas %}
            <div class="practice-area">
                <div class="practice-area-header">
                    <h3>{{ area }}</h3>
                </div>
                {% for change in changes %}
                    {% if area in change.practice_groups_names %}
                    <div class="relevance-explanation">
                        {{ get_practice_group_relevance(change, area) }}
                    </div>
                    <div class="impact-analysis">
                        {{ format_analysis_section_html(change.impact_analysis)|safe }}
                    </div>
                    {% endif %}
                {% endfor %}
            </div>
            {% endfor %}

            {% if no_impact_changes %}
            <div class="no-impact-section">
                <h3>Changes with No Local Agency Impact</h3>
                {% for change in no_impact_changes %}
                <div class="no-impact-item">
                    <p class="summary">{{ get_no_impact_summary(change) }}</p>
                    <p>Change:</p>
                    <div>
                        {{ format_analysis_section_html(change.digest_text)|safe }}
                    </div>
                </div>
                {% endfor %}
            </div>
            {% endif %}
        </body>
        </html>
        """

    def _get_default_css(self) -> str:
        """
        Return the default CSS styles for the report.
        FIXED: Use proper syntax for `content:` in margin boxes.
        """
        return r"""
        @page {
            margin: 1in;
            @top-center {
                /* Use double quotes or single quotes consistently */
                content: "Bill Analysis Report";
                font-family: Arial, sans-serif;
                font-size: 10pt;
            }
            @bottom-right {
                /* Example of including text + page counter */
                content: "Page " counter(page);
                font-family: Arial, sans-serif;
                font-size: 10pt;
            }
        }

        body {
            font-family: Arial, sans-serif;
            font-size: 11pt;
            line-height: 1.5;
            color: #333333;
        }

        h1 {
            color: #1a5f7a;
            font-size: 24pt;
            margin-bottom: 20px;
            border-bottom: 2px solid #1a5f7a;
            padding-bottom: 5px;
        }

        h2 {
            color: #1a5f7a;
            font-size: 18pt;
            margin-top: 30px;
            margin-bottom: 15px;
            border-bottom: 1px solid #1a5f7a;
            padding-bottom: 3px;
        }

        h3 {
            color: #2c3e50;
            font-size: 14pt;
            margin-top: 20px;
            margin-bottom: 10px;
        }

        h4 {
            color: #2c3e50;
            font-size: 12pt;
            margin-top: 15px;
            margin-bottom: 8px;
        }

        .header-info {
            margin-bottom: 30px;
            padding: 15px;
            background-color: #f8f9fa;
            border-radius: 5px;
        }

        .header-info p {
            margin: 5px 0;
        }

        .executive-summary {
            margin: 20px 0;
            padding: 15px;
            background-color: #f1f7fa;
            border-radius: 5px;
            border: 1px solid #dee2e6;
        }

        .practice-area {
            margin: 20px 0;
            padding: 15px;
            background-color: #ffffff;
            border: 1px solid #dee2e6;
            border-radius: 5px;
        }

        .practice-area-header {
            background-color: #1a5f7a;
            color: white;
            padding: 10px;
            margin: -15px -15px 15px -15px;
            border-radius: 5px 5px 0 0;
        }

        .relevance-explanation {
            background-color: #e9ecef;
            padding: 10px;
            margin: 10px 0;
            border-left: 4px solid #1a5f7a;
        }

        .impact-analysis {
            margin: 15px 0;
            padding: 10px;
            border-left: 4px solid #6c757d;
            background-color: #fafafa;
            border-radius: 5px;
        }

        .impact-analysis ul {
            margin-left: 1.2em;
        }

        .no-impact-section {
            margin: 20px 0;
            padding: 15px;
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 5px;
        }

        .no-impact-item {
            margin: 10px 0;
            padding: 10px;
            background-color: #ffffff;
            border-left: 4px solid #6c757d;
            border-radius: 5px;
        }

        .summary {
            font-weight: bold;
            color: #2c3e50;
        }
        """
