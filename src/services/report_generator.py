import logging
import re
from typing import Dict, Any, List, Union
from datetime import datetime
from weasyprint import HTML, CSS
import os
from jinja2 import Environment, FileSystemLoader

class ReportGenerator:
    """
    Generates formatted reports from analyzed bill data.
    Can produce text, HTML, or PDF outputs.
    """

    def __init__(self):
        """Initialize the report generator with a logger and Jinja environment."""
        self.logger = logging.getLogger(__name__)

        # We will look for 'templates' in the same directory as this file unless changed
        # Adjust if needed depending on your project structure
        template_dir = os.path.join(os.path.dirname(__file__), 'templates')

        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True
        )

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def generate_report(
        self,
        analyzed_skeleton: Dict[str, Any],
        bill_info: Dict[str, Any],
        bill_text: str,
        output_format: str = "html"
    ) -> Union[str, bytes]:
        """Generate a report in the specified format."""
        try:
            # Process the bill text into sections for reference
            bill_sections = self._process_bill_sections(bill_text)

            # Prepare template data
            template_data = self._prepare_template_data(
                analyzed_skeleton, 
                bill_info,
                bill_sections
            )

            if output_format == "html":
                return self._generate_html_report(template_data)
            elif output_format == "pdf":
                html_content = self._generate_html_report(template_data)
                return self._convert_to_pdf(html_content)
            else:
                raise ValueError(f"Unsupported output format: {output_format}")

        except Exception as exc:
            self.logger.error(f"Error generating {output_format} report: {str(exc)}")
            raise

    def save_report(self, report_content: Union[str, bytes], filename: str) -> None:
        """Save the report to a file."""
        mode = 'wb' if isinstance(report_content, bytes) else 'w'
        try:
            with open(filename, mode) as f:
                f.write(report_content)
        except Exception as exc:
            self.logger.error(f"Error saving report: {str(exc)}")
            raise

    # ----------------------------------------------------------------------
    # Internal Processing
    # ----------------------------------------------------------------------

    def _process_bill_sections(self, bill_text: str) -> Dict[str, Dict[str, Any]]:
        """
        Process bill text into a dictionary of sections with metadata.

        Returns:
            Dict with structure:
            {
                "section_number": {
                    "text": "full text of section",
                    "code": "Government Code/Public Resources Code/etc",
                    "section_number": "referenced code section number",
                    "action": "amended/added/repealed"
                }
            }
        """
        sections = {}
        try:
            # Pattern matches both "SECTION X." and "SEC. X." followed by text
            pattern = r'^(?:SECTION|SEC\.)\s+(\d+)\.?\s+(.*?)(?=^(?:SECTION|SEC\.)|$)'

            matches = re.finditer(pattern, bill_text, re.MULTILINE | re.DOTALL)

            for match in matches:
                section_num = match.group(1)
                full_text = match.group(2).strip()

                # Regex to parse first line to get code reference and action
                first_line_pattern = r'Section\s+(\d+(?:\.\d+)?)\s+(?:of\s+the\s+)?([A-Za-z\s]+Code)\s+is\s+(\w+)'
                code_match = re.search(first_line_pattern, full_text)

                sections[section_num] = {
                    "text": full_text,
                    "code": code_match.group(2) if code_match else None,
                    "section_number": code_match.group(1) if code_match else None,
                    "action": code_match.group(3) if code_match else None
                }

            self.logger.info(f"Processed {len(sections)} bill sections")
            return sections

        except Exception as exc:
            self.logger.error(f"Error processing bill sections: {str(exc)}")
            self.logger.debug(f"Bill text preview: {bill_text[:500]}")
            return {}

    def _prepare_template_data(
        self,
        analyzed_skeleton: Dict[str, Any],
        bill_info: Dict[str, Any],
        bill_sections: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Prepare data for rendering in the report template."""
        # Get the date in proper format
        date_approved = self._format_date(bill_info.get('date_approved'))

        changes = []
        for change in analyzed_skeleton.get('changes', []):
            processed_change = {
                'id': change.get('id', ''),
                'impacts_local_agencies': change.get('impacts_local_agencies', False),
                'bill_sections': change.get('bill_sections', []),
                'substantive_change': change.get('substantive_change', ''),
                'local_agency_impact': change.get('local_agency_impact', ''),
                'analysis': change.get('analysis', ''),
                'key_action_items': change.get('key_action_items', []),
                'practice_groups': change.get('practice_groups', []),
                'impacted_agencies': change.get('impacted_agencies', [])
            }

            # Attach section details
            section_details = []
            for sec_num in processed_change['bill_sections']:
                if sec_num in bill_sections:
                    section_details.append({
                        'number': sec_num,
                        'text': bill_sections[sec_num].get('text', ''),
                        'code': bill_sections[sec_num].get('code', ''),
                        'action': bill_sections[sec_num].get('action', '')
                    })
            processed_change['section_details'] = section_details

            changes.append(processed_change)

        # Now separate changes by local agency impact
        no_impact_changes = [c for c in changes if not c['impacts_local_agencies']]
        impacting_changes = [c for c in changes if c['impacts_local_agencies']]

        # Collect all practice groups (that appear as primary) among the changes that do impact local agencies
        practice_groups_affected = sorted(list(set(
            pg['name'] for c in impacting_changes for pg in c['practice_groups'] if pg.get('relevance') == 'primary'
        )))

        # Group changes by their primary practice groups
        grouped_changes = {}
        general_local_agency_impact_changes = []

        for c in impacting_changes:
            primary_pgs = [pg['name'] for pg in c.get('practice_groups', []) if pg.get('relevance') == 'primary']
            if not primary_pgs:
                # No primary group assigned, but it does impact local agencies
                general_local_agency_impact_changes.append(c)
            else:
                for pg_name in primary_pgs:
                    if pg_name not in grouped_changes:
                        grouped_changes[pg_name] = []
                    grouped_changes[pg_name].append(c)

        # Template data
        return {
            'bill_info': bill_info,
            'date_approved': date_approved,
            'total_changes': len(changes),
            'impacting_changes': len(impacting_changes),
            'practice_areas': practice_groups_affected,
            'changes': changes,
            'no_impact_changes': no_impact_changes,
            'grouped_changes': grouped_changes,
            'general_local_agency_impact_changes': general_local_agency_impact_changes
        }

    def _generate_html_report(self, template_data: Dict[str, Any]) -> str:
        """Generate HTML report using the Jinja template."""
        try:
            # Add custom template filters
            def format_section_reference(section):
                if isinstance(section, dict):
                    return f"{section.get('code', '')} Section {section.get('number', '')}"
                return str(section)

            self.jinja_env.filters['format_section'] = format_section_reference
            self.jinja_env.filters['format_analysis'] = self._format_analysis_section_html

            template = self.jinja_env.get_template('report.html')
            rendered_html = template.render(**template_data)
            return rendered_html

        except Exception as exc:
            self.logger.error(f"Error generating HTML report: {str(exc)}")
            self.logger.exception(exc)
            raise

    def _convert_to_pdf(self, html_content: str) -> bytes:
        """Convert HTML report to PDF."""
        try:
            html = HTML(string=html_content)
            return html.write_pdf()
        except Exception as exc:
            self.logger.error(f"Error converting to PDF: {str(exc)}")
            raise

    # ----------------------------------------------------------------------
    # Formatting Helpers
    # ----------------------------------------------------------------------

    def _format_date(self, date: Any) -> str:
        """Format a date for display in the report."""
        if isinstance(date, datetime):
            return date.strftime('%B %d, %Y')
        return 'Not Available'

    def _format_analysis_section_html(self, analysis_text: str) -> str:
        """Convert raw analysis text into formatted HTML."""
        if not analysis_text:
            return ""
        lines = self._extract_lines(analysis_text)
        return self._process_subheadings_and_bullets_html(lines)

    def _extract_lines(self, raw_text: str) -> List[str]:
        """Extract non-empty lines from text, stripping out HTML tags."""
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
