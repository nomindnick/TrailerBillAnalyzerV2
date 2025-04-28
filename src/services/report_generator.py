import os
import logging
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Dict, List, Any, Optional

class ReportGenerator:
    """Generates HTML reports from analyzed bills"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Get the directory of this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        templates_dir = os.path.join(current_dir, 'templates')

        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(['html', 'xml'])
        )

        # CSS styles to be inlined in the HTML template
        self.css_styles = """
            /* Base styles */
            @page {
                margin: 2cm;
                @bottom-center {
                    content: "Page " counter(page) " of " counter(pages);
                    font-size: 10pt;
                    color: #666;
                }
            }
            
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f9f9f9;
            }
            
            /* Header styles */
            .header {
                text-align: center;
                margin-bottom: 2rem;
                padding-bottom: 1rem;
                border-bottom: 2px solid #ddd;
                page-break-after: avoid;
            }
            
            .bill-title {
                font-size: 2rem;
                color: #2c3e50;
                margin-bottom: 0.75rem;
                line-height: 1.2;
            }
            
            .subtitle {
                font-size: 1.2rem;
                color: #7f8c8d;
                margin-bottom: 0.5rem;
            }
            
            /* Summary section */
            .metadata {
                background-color: #f5f5f5;
                padding: 1.25rem;
                border-radius: 5px;
                margin-bottom: 2rem;
                border-left: 4px solid #3498db;
                page-break-inside: avoid;
            }
            
            .summary-section {
                margin-bottom: 2rem;
                background-color: #fff;
                padding: 1.5rem;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                page-break-inside: avoid;
            }
            
            .summary-header {
                margin-top: 0;
                color: #2c3e50;
                border-bottom: 2px solid #ecf0f1;
                padding-bottom: 0.75rem;
                font-size: 1.5rem;
            }
            
            /* Change boxes */
            .change-boxes {
                display: flex;
                flex-direction: column;
                gap: 2.5rem;
            }
            
            .change-box {
                border: 1px solid #ddd;
                border-radius: 5px;
                overflow: hidden;
                background-color: #fff;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                margin-bottom: 2rem;
                page-break-inside: avoid;
            }
            
            .change-header {
                background-color: #3498db;
                color: white;
                padding: 0.75rem 1.25rem;
                font-weight: bold;
                font-size: 1.2rem;
            }
            
            .change-content {
                padding: 1rem;
            }
            
            .change-box p {
                margin: 0.75rem 0;
            }
            
            .change-box h4 {
                color: #2c3e50;
                margin: 1.5rem 0 0.75rem 0;
                font-size: 1.15rem;
                border-bottom: 1px solid #eee;
                padding-bottom: 0.4rem;
            }
            
            /* Lists */
            .change-box ul {
                margin: 0.75rem 0;
                padding-left: 2rem;
            }
            
            .change-box ul li {
                margin-bottom: 0.5rem;
                position: relative;
                list-style-type: disc;
            }
            
            .change-box ul li::marker {
                content: "• ";
                color: #3498db;
                font-weight: bold;
            }
            
            /* Practice areas */
            .practice-areas {
                margin: 1.5rem 0;
                background-color: #f8f9fa;
                padding: 1.25rem;
                border-radius: 5px;
                border-left: 4px solid #2ecc71;
            }
            
            .practice-area {
                display: inline-block;
                background-color: #e1f5fe;
                padding: 0.4rem 0.7rem;
                margin: 0.3rem;
                border-radius: 3px;
                font-size: 0.9rem;
                color: #0288d1;
            }
            
            .primary-area {
                background-color: #b3e5fc;
                color: #01579b;
                font-weight: bold;
            }
            
            /* Section information */
            .section-list {
                background-color: #f5f5f5;
                padding: 1rem 1.25rem;
                margin: 1rem 0;
                border-radius: 5px;
                font-size: 0.95rem;
            }
            
            .section-reference {
                font-weight: bold;
                color: #e74c3c;
            }
            
            .bill-text-section {
                background-color: #f9f9f9;
                border-left: 3px solid #ccc;
                padding: 1.25rem;
                margin: 1rem 0;
                font-family: monospace;
                font-size: 0.9rem;
                overflow-x: auto;
                white-space: pre-wrap;
            }
            
            /* Action items */
            .action-items {
                background-color: #fff3e0;
                padding: 1.25rem;
                margin: 1.25rem 0;
                border-radius: 5px;
                border-left: 4px solid #ff9800;
            }
            
            .deadline {
                color: #d32f2f;
                font-weight: bold;
            }
            
            /* Section headers */
            .report-section {
                margin-bottom: 3.5rem;
                page-break-before: auto;
            }
            
            .report-section-title {
                background-color: #2c3e50;
                color: white;
                padding: 1.25rem;
                margin: 2.5rem 0 1.75rem 0;
                border-radius: 5px;
                font-size: 1.5rem;
                box-shadow: 0 3px 6px rgba(0,0,0,0.1);
                page-break-after: avoid;
            }
                        
            /* Footer */
            .footer {
                margin-top: 3.5rem;
                text-align: center;
                font-size: 0.9rem;
                color: #7f8c8d;
                padding-top: 1rem;
                border-top: 1px solid #ddd;
            }
            
            /* Print-specific styles */
            @media print {
                body {
                    padding: 0;
                    background: white;
                    font-size: 12pt;
                    color: black;
                }
                
                .change-box {
                    break-inside: avoid;
                    page-break-inside: avoid;
                    margin-bottom: 20mm;
                    border: 1px solid #ccc;
                }
                
                .change-header {
                    background-color: #3498db !important;
                    color: white !important;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
                
                .header, 
                .metadata, 
                .summary-section, 
                .practice-areas {
                    page-break-inside: avoid;
                }
                
                .report-section-title {
                    page-break-after: avoid;
                    background-color: #2c3e50 !important;
                    color: white !important;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
                
                .action-items {
                    page-break-inside: avoid;
                    background-color: #fff3e0 !important;
                    border-left: 4px solid #ff9800 !important;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
                
                a {
                    text-decoration: underline;
                    color: blue !important;
                }
                
                .change-box ul li {
                    list-style-type: disc !important;
                }
                
                .change-box ul li::before {
                    content: "• ";
                    color: #3498db !important;
                    font-weight: bold;
                    display: inline-block; 
                    width: 1em;
                    margin-left: -1em;
                }
                
                .section-list,
                .practice-areas {
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
            }
        """

    def generate_report(self, analyzed_data: Dict[str, Any], bill_info: Dict[str, Any], bill_text: str) -> str:
        """
        Generate an HTML report from the analyzed bill data

        Args:
            analyzed_data: The data structure with analysis results
            bill_info: Basic information about the bill
            bill_text: Full text of the bill

        Returns:
            HTML report as a string
        """
        try:
            template = self.env.get_template('report.html')

            # Extract practice areas
            practice_areas = analyzed_data["metadata"].get("practice_groups_affected", [])

            # Check and set defaults for key values
            bill_info.setdefault("date_approved", "N/A")
            bill_info.setdefault("chapter_number", "N/A")
            bill_info.setdefault("title", "Untitled")

            # Prepare sections with their text for display
            sections = []
            for change in analyzed_data["changes"]:
                if "bill_sections" in change:
                    for sec in change.get("bill_section_details", []):
                        sec_obj = {
                            "number": sec["number"],
                            "text": sec["text"],
                            "original_label": sec.get("original_label", f"Section {sec['number']}")
                        }
                        sections.append(sec_obj)

            # Get model display name for the report
            model_name = bill_info.get("model", "gpt-4o")
            model_display_name = self._get_model_display_name(model_name)

            # Group changes by practice group
            practice_group_changes = {}
            no_local_impact_changes = []

            for change in analyzed_data["changes"]:
                # CRITICAL FIX: First check for no impact flag before practice group sorting
                if not change.get("impacts_local_agencies", False):
                    # If explicitly marked as no impact, add to no_local_impact section
                    no_local_impact_changes.append(change)
                    continue

                # For changes with impact, sort by practice group
                if "practice_groups" in change and change["practice_groups"]:
                    # Find primary practice group
                    primary_group = None
                    for pg in change["practice_groups"]:
                        if pg["relevance"].lower() == "primary":
                            primary_group = pg["name"]
                            break

                    # If found a primary group, add to that group's changes
                    if primary_group:
                        if primary_group not in practice_group_changes:
                            practice_group_changes[primary_group] = []
                        practice_group_changes[primary_group].append(change)
                    else:
                        # If no primary practice group found, add to no impact
                        # (this should be rare but provides a fallback)
                        no_local_impact_changes.append(change)
                else:
                    # If no practice groups at all, add to no impact
                    no_local_impact_changes.append(change)

            # Create report sections organized by practice group
            formatted_sections = []

            # Add practice group sections first
            for group_name, changes in practice_group_changes.items():
                formatted_sections.append({
                    "title": f"Practice Group: {group_name}",
                    "content": {"changes": changes}
                })

            # Add "No Local Government Impacts" section at the end
            if no_local_impact_changes:
                formatted_sections.append({
                    "title": "No Local Government Impacts",
                    "content": {"changes": no_local_impact_changes}
                })

            rendered = template.render(
                bill_info=bill_info,
                metadata=analyzed_data["metadata"],
                changes=analyzed_data["changes"],
                state_summary="N/A",
                practice_areas=analyzed_data["metadata"].get("practice_groups_affected", []),
                report_sections=formatted_sections,
                now=datetime.now().strftime("%B %d, %Y"),
                ai_model=model_display_name,
                css_styles=self.css_styles
            )

            return rendered

        except Exception as e:
            self.logger.error(f"Error generating report: {str(e)}")
            raise

    def _get_model_display_name(self, model_name: str) -> str:
        """Convert internal model name to a display-friendly version"""
        model_display_map = {
            "gpt-4.1-2025-04-14": "GPT-4.1 (April 2025)",
            "gpt-4-turbo": "GPT-4 Turbo",
            "gpt-3.5-turbo": "GPT-3.5 Turbo",
            "o4-mini-2025-04-16": "GPT-o4-mini (April 2025)",
            "claude-3-opus-20240229": "Claude 3 Opus",
            "claude-3-sonnet-20240229": "Claude 3 Sonnet",
            "claude-3-7-sonnet-20250219": "Claude 3.7 Sonnet (Deep Thinking)"
        }

        return model_display_map.get(model_name, model_name)

    def save_report(self, html_content: str, file_path: str) -> None:
        """
        Save the HTML report to a file

        Args:
            html_content: The HTML report content
            file_path: The path to save the file to
        """
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"Report saved to {file_path}")
        except Exception as e:
            self.logger.error(f"Error saving report: {str(e)}")
            raise

    def _register_custom_filters(self) -> None:
        self.env.filters.update({
            "format_analysis": self._format_analysis
        })

    def _format_analysis(self, text: str) -> str:
        return text