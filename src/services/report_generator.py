import logging
import re
from typing import Dict, Any, List, Union
from datetime import datetime
from weasyprint import HTML, CSS
from jinja2 import Environment, select_autoescape

class ReportGenerator:
    """Generates formatted reports from analyzed bill data."""

    def __init__(self):
        """Initialize the report generator with a logger."""
        self.logger = logging.getLogger(__name__)

        # CSS styles for the report - slightly tweaked for a cleaner look
        self.css_styles = """
        @page {
            margin: 1in;
            @top-center {
                content: "Bill Analysis Report";
                font-family: Arial, sans-serif;
                font-size: 10pt;
            }
            @bottom-right {
                content: counter(page);
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

    def generate_report(
        self,
        analyzed_skeleton: Dict[str, Any],
        bill_info: Dict[str, Any],
        output_format: str = "text"
    ) -> Union[str, bytes]:
        """
        Generate a report in the specified format.

        Args:
            analyzed_skeleton: The analyzed bill data
            bill_info: Basic information about the bill
            output_format: "text", "html", or "pdf"

        Returns:
            str for text/html formats, bytes for PDF format
        """
        try:
            if output_format == "text":
                return self._generate_text_report(analyzed_skeleton, bill_info)
            elif output_format == "html":
                return self._generate_html_content(analyzed_skeleton, bill_info)
            elif output_format == "pdf":
                html_content = self._generate_html_content(analyzed_skeleton, bill_info)
                return self._convert_to_pdf(html_content)
            else:
                raise ValueError(f"Unsupported output format: {output_format}")

        except Exception as e:
            self.logger.error(f"Error generating report: {str(e)}")
            raise

    def save_report(self, report_content: Union[str, bytes], filename: str) -> None:
        """
        Save the report to a file.
        Automatically switches to binary mode if the content is bytes.
        """
        mode = 'wb' if isinstance(report_content, bytes) else 'w'
        try:
            with open(filename, mode) as f:
                f.write(report_content)
        except Exception as e:
            self.logger.error(f"Error saving report: {str(e)}")
            raise

    # -------------------------------------------------------------------------
    # FORMATTING HELPER METHODS
    # -------------------------------------------------------------------------

    def _extract_lines(self, raw_text: str) -> List[str]:
        """
        Splits text into a list of non-empty lines, stripped of XML tags.
        """
        if not raw_text:
            return []

        # Remove tags like <detailed_analysis> or anything else
        text_no_tags = re.sub(r'<[^>]+>', '', raw_text)
        # Split into lines
        lines = [l.strip() for l in text_no_tags.split('\n') if l.strip()]
        return lines

    def _process_subheadings_and_bullets_html(self, lines: List[str]) -> str:
        """
        Processes lines such that lines ending with a colon (e.g., "Affected Local Agencies:")
        become subheadings (<h4>), and the subsequent lines become bullets unless
        they themselves are subheadings.

        Returns a chunk of HTML.
        """
        html_output = []
        in_list = False

        for line in lines:
            # Check if line is a subheading (ends with a colon)
            if line.endswith(':'):
                # Close any open bullet list
                if in_list:
                    html_output.append("</ul>")
                    in_list = False
                # Output as subheading
                # e.g. "Affected Local Agencies:"
                subheading_text = line[:-1]  # remove the colon
                html_output.append(f"<h4>{subheading_text}</h4>")
            else:
                # It's not a subheading, so we treat it as a bullet line
                if not in_list:
                    html_output.append("<ul>")
                    in_list = True
                # Actually produce a bullet item
                html_output.append(f"<li>{line}</li>")

        if in_list:
            html_output.append("</ul>")

        return "\n".join(html_output)

    def _process_subheadings_and_bullets_text(self, lines: List[str]) -> str:
        """
        Processes lines for text output. Subheadings (ending in a colon)
        become uppercase lines; subsequent lines are converted into bullets.
        """
        output_lines = []
        in_bullet_block = False

        for line in lines:
            if line.endswith(':'):
                # close the bullet block if open
                if in_bullet_block:
                    in_bullet_block = False
                    output_lines.append("")  # blank line for spacing

                # Use subheading style for plain text
                subheading_text = line[:-1].upper()
                output_lines.append(subheading_text)
                output_lines.append("-" * len(subheading_text))
            else:
                # bullet line
                if not in_bullet_block:
                    in_bullet_block = True
                output_lines.append(f"  • {line}")

        return "\n".join(output_lines)

    def _format_analysis_section_html(self, analysis_text: str) -> str:
        """
        Format an analysis section for HTML output:
          - strips any XML tags
          - separates subheadings (ending with a colon) from bullet lines
        """
        lines = self._extract_lines(analysis_text)
        return self._process_subheadings_and_bullets_html(lines)

    def _format_analysis_section_text(self, analysis_text: str) -> str:
        """
        Format an analysis section for text output:
          - strips any XML tags
          - subheadings vs bullet lines
        """
        lines = self._extract_lines(analysis_text)
        return self._process_subheadings_and_bullets_text(lines)

    def _format_change_header(self, change: Dict[str, Any]) -> str:
        """
        Format the header for each change, including bill section references.
        """
        section_refs = change.get('bill_sections', [])
        section_text = f"[Bill Sections: {', '.join(section_refs)}]" if section_refs else ""
        return f"\n{section_text}\n"

    def _generate_practice_group_relevance(self, change: Dict[str, Any], practice_group: str) -> str:
        """
        Generate explanation of why a change is relevant to a specific practice group.
        """
        pg_entry = next(
            (pg for pg in change.get("practice_groups", []) if pg["name"] == practice_group),
            None
        )

        if not pg_entry:
            return ""

        relevance_level = pg_entry.get("relevance", "")

        relevance_explanations = {
            "Business and Facilities": {
                "primary": (
                    "This change directly affects the business operations and facilities "
                    "management of local agencies through impacts on infrastructure, procurement, "
                    "or operational requirements."
                ),
                "secondary": (
                    "This change has indirect implications for local agency business operations "
                    "or facilities management through modified procedures or optional opportunities."
                )
            },
            "Public Finance": {
                "primary": (
                    "This change has direct fiscal implications for local agencies, affecting "
                    "their funding mechanisms, financial obligations, or budget requirements."
                ),
                "secondary": (
                    "This change presents potential financial considerations for local agencies "
                    "through optional programs or indirect fiscal effects."
                )
            },
            # Add or edit practice group entries as necessary
        }

        base_explanation = relevance_explanations.get(practice_group, {}).get(relevance_level, "")
        if not base_explanation:
            return ""

        return f"Practice Group Relevance ({relevance_level.title()}): {base_explanation}"

    def _generate_no_impact_summary(self, change: Dict[str, Any]) -> str:
        """
        Generate a summary explaining why a change has no local agency impact.
        """
        digest_text = change.get('digest_text', '')

        state_only_indicators = [
            "state agency", "state department", "state entity",
            "Department of ", "state vehicle fleet", "High-Speed Rail Authority"
        ]

        is_state_only = any(indicator.lower() in digest_text.lower() for indicator in state_only_indicators)
        if is_state_only:
            return "This change affects only state-level agencies and operations, with no direct impact on local agencies."

        if "technical" in digest_text.lower() or "administrative" in digest_text.lower():
            return "This is a technical or administrative change that does not affect local agency operations or requirements."

        return "This change does not create any new requirements, modify existing obligations, or directly affect the operations of local agencies."

    # -------------------------------------------------------------------------
    # REPORT GENERATION METHODS (TEXT/HTML)
    # -------------------------------------------------------------------------

    def _generate_text_report(self, analyzed_skeleton: Dict[str, Any], bill_info: Dict[str, Any]) -> str:
        """
        Generate a plain text report.
        """
        try:
            sections = []
            # Header
            sections.append(self._generate_header(bill_info))
            # Executive Summary
            sections.append(self._generate_executive_summary(analyzed_skeleton))
            # Practice Area Analysis
            sections.append(self._generate_practice_area_analysis_text(analyzed_skeleton))

            return "\n\n".join(sections)

        except Exception as e:
            self.logger.error(f"Error generating text report: {str(e)}")
            raise

    def _generate_header(self, bill_info: Dict[str, Any]) -> str:
        """
        Generate the report header for text output.
        """
        return (
            f"BILL ANALYSIS REPORT\n"
            f"{'-' * 50}\n"
            f"Bill Number: {bill_info['bill_number']}\n"
            f"Chapter Number: {bill_info['chapter_number']}\n"
            f"Title: {bill_info['title']}\n"
            f"Date Approved: {bill_info['date_approved'].strftime('%Y-%m-%d')}"
        )

    def _generate_executive_summary(self, analyzed_skeleton: Dict[str, Any]) -> str:
        """
        Generate the executive summary section for text output.
        """
        return (
            f"EXECUTIVE SUMMARY\n"
            f"{'-' * 50}\n"
            f"Total Changes: {len(analyzed_skeleton['changes'])}\n"
            f"Changes Impacting Local Agencies: "
            f"{sum(1 for c in analyzed_skeleton['changes'] if c.get('impacts_local_agencies'))}\n"
            f"Practice Areas Affected: "
            f"{', '.join(analyzed_skeleton['metadata']['practice_groups_affected'])}"
        )

    def _generate_practice_area_analysis_text(self, analyzed_skeleton: Dict[str, Any]) -> str:
        """
        Generate the analysis by practice area section for text output.
        """
        sections = []
        sections.append("ANALYSIS BY PRACTICE AREA")
        sections.append("=" * 24)

        impacting_changes = [
            c for c in analyzed_skeleton['changes']
            if c.get('impacts_local_agencies')
        ]

        affected_areas = analyzed_skeleton['metadata']['practice_groups_affected']

        for area in affected_areas:
            sections.append(self._generate_practice_area_section_text(area, impacting_changes))

        no_impact_changes = [
            c for c in analyzed_skeleton['changes']
            if not c.get('impacts_local_agencies')
        ]
        if no_impact_changes:
            sections.append(self._generate_no_impact_section_text(no_impact_changes))

        return "\n".join(sections)

    def _generate_practice_area_section_text(self, area: str, changes: List[Dict[str, Any]]) -> str:
        """
        Generate text for a specific practice area's impacted changes.
        """
        sections = [f"\n{area.upper()}"]
        sections.append("=" * len(area))

        for change in changes:
            if not any(pg['name'] == area for pg in change.get('practice_groups', [])):
                continue

            sections.append(self._format_change_header(change))

            relevance = next(
                (pg['relevance'] for pg in change.get('practice_groups', [])
                 if pg['name'] == area),
                'unknown'
            )
            sections.append(f"Relevance Level: {relevance.title()}")

            if change.get('impact_analysis'):
                sections.append("\nImpact Analysis:")
                formatted_analysis = self._format_analysis_section_text(change['impact_analysis'])
                sections.append(formatted_analysis)

            sections.append("\n" + "-" * 80 + "\n")

        return '\n'.join(sections)

    def _generate_no_impact_section_text(self, changes: List[Dict[str, Any]]) -> str:
        """
        Generate text for changes with no local agency impact.
        """
        if not changes:
            return ""

        sections = ["\nCHANGES WITH NO LOCAL AGENCY IMPACT"]
        sections.append("=" * 31)

        for change in changes:
            sections.append(self._format_change_header(change))
            sections.append("Summary:")
            digest_formatted = self._format_analysis_section_text(change.get('digest_text', ''))
            sections.append(digest_formatted)
            sections.append("\n" + "-" * 80 + "\n")

        return '\n'.join(sections)

    def _generate_html_content(self, analyzed_skeleton: Dict[str, Any], bill_info: Dict[str, Any]) -> str:
        """
        Generate formatted HTML content, with improved cleaning/formatting of analysis sections.
        """
        html_template = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Bill Analysis Report - {{bill_info.bill_number}}</title>
            <style>
                {{css_styles}}
            </style>
        </head>
        <body>
            <h1>Bill Analysis Report</h1>

            <div class="header-info">
                <p><strong>Bill Number:</strong> {{bill_info.bill_number}}</p>
                <p><strong>Chapter Number:</strong> {{bill_info.chapter_number}}</p>
                <p><strong>Title:</strong> {{bill_info.title}}</p>
                <p><strong>Date Approved:</strong> {{bill_info.date_approved.strftime('%Y-%m-%d')}}</p>
            </div>

            <div class="executive-summary">
                <h2>Executive Summary</h2>
                <p><strong>Total Changes:</strong> {{total_changes}}</p>
                <p><strong>Changes Impacting Local Agencies:</strong> {{impacting_changes}}</p>
                <p><strong>Practice Areas Affected:</strong> {{practice_areas|join(', ')}}</p>
            </div>

            <h2>Analysis by Practice Area</h2>
            {% for area in practice_areas %}
            <div class="practice-area">
                <div class="practice-area-header">
                    <h3>{{area}}</h3>
                </div>
                {% for change in changes %}
                    {% if area in change.practice_groups_names %}
                    <div class="relevance-explanation">
                        {{get_practice_group_relevance(change, area)}}
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
                    <p class="summary">{{get_no_impact_summary(change)}}</p>
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

        # Add practice_groups_names to each change for easier template handling
        for change in analyzed_skeleton['changes']:
            change['practice_groups_names'] = [
                pg['name']
                for pg in change.get('practice_groups', [])
            ]

        # Prepare template data
        template_data = {
            'css_styles': self.css_styles,
            'bill_info': bill_info,
            'total_changes': len(analyzed_skeleton['changes']),
            'impacting_changes': sum(
                1 for c in analyzed_skeleton['changes'] if c.get('impacts_local_agencies')
            ),
            'practice_areas': analyzed_skeleton['metadata']['practice_groups_affected'],
            'changes': [
                change for change in analyzed_skeleton['changes']
                if change.get('impacts_local_agencies')
            ],
            'no_impact_changes': [
                change for change in analyzed_skeleton['changes']
                if not change.get('impacts_local_agencies')
            ],
            'get_practice_group_relevance': self._generate_practice_group_relevance,
            'get_no_impact_summary': self._generate_no_impact_summary,
            # Our improved function for subheadings + bullet points
            'format_analysis_section_html': self._format_analysis_section_html
        }

        env = Environment(autoescape=select_autoescape(['html', 'xml']))
        template = env.from_string(html_template)
        return template.render(**template_data)

    # -------------------------------------------------------------------------
    # HTML/PDF SPECIFIC METHODS
    # -------------------------------------------------------------------------

    def _convert_to_pdf(self, html_content: str) -> bytes:
        """
        Convert HTML content to PDF using WeasyPrint.
        """
        try:
            html = HTML(string=html_content)
            css = CSS(string=self.css_styles)
            return html.write_pdf(stylesheets=[css])
        except Exception as e:
            self.logger.error(f"Error converting to PDF: {str(e)}")
            raise