from typing import Dict, Any, List, Union, Optional, Set
from datetime import datetime
import logging
from jinja2 import Environment, FileSystemLoader, Template
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

    def generate_report(
        self,
        analyzed_data: Dict[str, Any],
        bill_info: Dict[str, Any],
        parsed_bill: Dict[str, Any],
        output_format: str = "html"
    ) -> Union[str, bytes]:
        """Generate enhanced report with better organization and formatting"""
        try:
            # Process data into report sections
            report_sections = self._organize_report_sections(
                analyzed_data,
                parsed_bill
            )

            # Prepare template data
            template_data = self._prepare_template_data(
                analyzed_data,
                bill_info,
                report_sections,
                parsed_bill
            )

            # Generate report in requested format
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
        """Organize changes into structured report sections"""
        sections = []

        # Group changes by practice group
        practice_group_changes = self._group_by_practice_group(
            analyzed_data["changes"]
        )

        # Create sections for each practice group
        for group, changes in practice_group_changes.items():
            sections.append(
                ReportSection(
                    title=group,
                    content=self._process_changes(changes, parsed_bill),
                    section_type="impact",
                    practice_group=group
                )
            )

        # Add section for general impacts (no specific practice group)
        general_impacts = self._get_general_impacts(analyzed_data["changes"])
        if general_impacts:
            sections.append(
                ReportSection(
                    title="General Local Agency Impact",
                    content=self._process_changes(general_impacts, parsed_bill),
                    section_type="impact"
                )
            )

        # Add section for non-impacting changes
        no_impact_changes = self._get_no_impact_changes(analyzed_data["changes"])
        if no_impact_changes:
            sections.append(
                ReportSection(
                    title="Changes with No Local Agency Impact",
                    content=self._process_changes(no_impact_changes, parsed_bill),
                    section_type="no_impact"
                )
            )

        return sections

    def _group_by_practice_group(
        self,
        changes: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group changes by primary practice group"""
        grouped = {}

        for change in changes:
            if change.get("impacts_local_agencies"):
                primary_groups = [
                    group["name"]
                    for group in change.get("practice_groups", [])
                    if group["relevance"] == "primary"
                ]

                for group in primary_groups:
                    if group not in grouped:
                        grouped[group] = []
                    grouped[group].append(change)

        return grouped

    def _process_changes(
        self,
        changes: List[Dict[str, Any]],
        parsed_bill: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Process changes with enhanced section information"""
        processed = []

        for change in changes:
            # Get linked bill sections
            section_details = self._get_section_details(
                change.get("bill_sections", []),
                parsed_bill
            )

            processed_change = {
                "id": change["id"],
                "substantive_change": change["substantive_change"],
                "local_agency_impact": change["local_agency_impact"],
                "section_details": section_details,
                "practice_groups": change.get("practice_groups", []),
                "key_action_items": change.get("key_action_items", []),
                "deadlines": change.get("deadlines", []),
                "requirements": change.get("requirements", [])
            }

            processed.append(processed_change)

        return processed

    def _get_section_details(
        self,
        section_numbers: List[str],
        parsed_bill: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get detailed information about bill sections"""
        details = []

        for num in section_numbers:
            if section := parsed_bill["bill_sections"].get(num):
                section_detail = {
                    "number": num,
                    "text": section["text"],
                    "code_modifications": []
                }

                # Add code modification details
                for mod in section.get("code_modifications", []):
                    section_detail["code_modifications"].append({
                        "code_name": mod.code_name,
                        "section": mod.section,
                        "action": mod.action
                    })

                details.append(section_detail)

        return details

    def _prepare_template_data(
        self,
        analyzed_data: Dict[str, Any],
        bill_info: Dict[str, Any],
        report_sections: List[ReportSection],
        parsed_bill: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare comprehensive data for report template"""
        return {
            "bill_info": bill_info,
            "metadata": analyzed_data["metadata"],
            "sections": report_sections,
            "practice_areas": sorted(list(set(
                section.practice_group
                for section in report_sections
                if section.practice_group
            ))),
            "date_generated": datetime.now().strftime("%B %d, %Y"),
            "bill_sections": parsed_bill["bill_sections"]
        }

    def _register_custom_filters(self) -> None:
        """Register custom Jinja filters for formatting"""
        self.jinja_env.filters.update({
            'format_date': self._format_date,
            'format_code_refs': self._format_code_references,
            'format_requirements': self._format_requirements,
            'format_deadlines': self._format_deadlines
        })

    def _format_date(self, date: Optional[datetime]) -> str:
        """Format date for display"""
        return date.strftime("%B %d, %Y") if date else "Not Available"

    def _format_code_references(
        self,
        modifications: List[Dict[str, Any]]
    ) -> str:
        """Format code references for display"""
        refs = []
        for mod in modifications:
            ref = f"{mod['code_name']} Section {mod['section']}"
            if mod.get('action'):
                ref += f" ({mod['action']})"
            refs.append(ref)
        return ", ".join(refs)

    def _format_requirements(
        self,
        requirements: List[str],
        indent: str = ""
    ) -> str:
        """Format requirements as HTML list"""
        if not requirements:
            return ""
        items = [f"{indent}<li>{req}</li>" for req in requirements]
        return f"{indent}<ul>\n{''.join(items)}\n{indent}</ul>"

    def _format_deadlines(
        self,
        deadlines: List[Dict[str, Any]]
    ) -> str:
        """Format deadlines as HTML table"""
        if not deadlines:
            return ""

        rows = []
        for deadline in deadlines:
            date = deadline.get("date", "")
            description = deadline.get("description", "")
            agencies = ", ".join(deadline.get("affected_agencies", []))

            rows.append(
                f"<tr>"
                f"<td>{date}</td>"
                f"<td>{description}</td>"
                f"<td>{agencies}</td>"
                f"</tr>"
            )

        return (
            "<table class='deadline-table'>"
            "<thead>"
            "<tr>"
            "<th>Date</th>"
            "<th>Requirement</th>"
            "<th>Affected Agencies</th>"
            "</tr>"
            "</thead>"
            "<tbody>"
            f"{''.join(rows)}"
            "</tbody>"
            "</table>"
        )

    def _generate_html_report(self, template_data: Dict[str, Any]) -> str:
        """Generate HTML report with improved formatting"""
        try:
            template = self.jinja_env.get_template('report.html')
            return template.render(**template_data)
        except Exception as e:
            self.logger.error(f"Error generating HTML report: {str(e)}")
            raise

    def _convert_to_pdf(self, html_content: str) -> bytes:
        """Convert HTML report to PDF with enhanced styling"""
        try:
            # Add print-specific CSS
            css = CSS(string="""
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
            """)

            html = HTML(string=html_content)
            return html.write_pdf(stylesheets=[css])

        except Exception as e:
            self.logger.error(f"Error converting to PDF: {str(e)}")
            raise

    def _get_general_impacts(
        self,
        changes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Get changes that impact agencies but have no primary practice group"""
        return [
            change for change in changes
            if change.get("impacts_local_agencies")
            and not any(
                group.get("relevance") == "primary"
                for group in change.get("practice_groups", [])
            )
        ]

    def _get_no_impact_changes(
        self,
        changes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Get changes that don't impact local agencies"""
        return [
            change for change in changes
            if not change.get("impacts_local_agencies")
        ]

    def save_report(
        self,
        report_content: Union[str, bytes],
        filename: str
    ) -> None:
        """Save report to file with error handling"""
        try:
            mode = 'wb' if isinstance(report_content, bytes) else 'w'
            with open(filename, mode, encoding='utf-8' if mode == 'w' else None) as f:
                f.write(report_content)
        except Exception as e:
            self.logger.error(f"Error saving report: {str(e)}")
            raise