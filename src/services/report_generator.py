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
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f9f9f9;
            }
            .header {
                text-align: center;
                margin-bottom: 2rem;
                padding-bottom: 1rem;
                border-bottom: 2px solid #ddd;
            }
            .bill-title {
                font-size: 1.8rem;
                color: #2c3e50;
                margin-bottom: 0.5rem;
            }
            .subtitle {
                font-size: 1.2rem;
                color: #7f8c8d;
                margin-bottom: 0.5rem;
            }
            .metadata {
                background-color: #f5f5f5;
                padding: 1rem;
                border-radius: 5px;
                margin-bottom: 2rem;
                border-left: 4px solid #3498db;
            }
            .summary-section {
                margin-bottom: 2rem;
                background-color: #fff;
                padding: 1.5rem;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }
            .summary-header {
                margin-top: 0;
                color: #2c3e50;
                border-bottom: 2px solid #ecf0f1;
                padding-bottom: 0.5rem;
            }
            .change-boxes {
                display: flex;
                flex-direction: column;
                gap: 2rem;
            }
            .change-box {
                border: 1px solid #ddd;
                border-radius: 5px;
                overflow: hidden;
                background-color: #fff;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            }
            .change-header {
                background-color: #3498db;
                color: white;
                padding: 0.75rem 1rem;
                font-weight: bold;
                font-size: 1.1rem;
            }
            .change-box p, .change-box h4, .change-box ul {
                padding: 0 1rem;
            }
            .change-box ul {
                padding-left: 3rem;
            }
            h4 {
                color: #2c3e50;
                margin-top: 1.5rem;
                margin-bottom: 0.5rem;
            }
            .practice-areas {
                margin-top: 1rem;
                background-color: #f8f9fa;
                padding: 1rem;
                border-radius: 5px;
                border-left: 4px solid #2ecc71;
            }
            .practice-area {
                display: inline-block;
                background-color: #e1f5fe;
                padding: 0.3rem 0.6rem;
                margin: 0.25rem;
                border-radius: 3px;
                font-size: 0.9rem;
                color: #0288d1;
            }
            .primary-area {
                background-color: #b3e5fc;
                color: #01579b;
                font-weight: bold;
            }
            .section-list {
                background-color: #f5f5f5;
                padding: 1rem;
                margin: 1rem;
                border-radius: 5px;
                font-size: 0.9rem;
            }
            .section-reference {
                font-weight: bold;
                color: #e74c3c;
            }
            .bill-text-section {
                background-color: #f9f9f9;
                border-left: 3px solid #ccc;
                padding: 1rem;
                margin: 1rem;
                font-family: monospace;
                font-size: 0.9rem;
                overflow-x: auto;
                white-space: pre-wrap;
            }
            .footer {
                margin-top: 3rem;
                text-align: center;
                font-size: 0.9rem;
                color: #7f8c8d;
                padding-top: 1rem;
                border-top: 1px solid #ddd;
            }
            .action-items {
                background-color: #fff3e0;
                padding: 1rem;
                margin: 1rem;
                border-radius: 5px;
                border-left: 4px solid #ff9800;
            }
            .deadline {
                color: #d32f2f;
                font-weight: bold;
            }
            .report-section {
                margin-bottom: 3rem;
            }
            .report-section-title {
                background-color: #2c3e50;
                color: white;
                padding: 1rem;
                margin-top: 2rem;
                margin-bottom: 1.5rem;
                border-radius: 5px;
                font-size: 1.4rem;
                box-shadow: 0 3px 6px rgba(0,0,0,0.1);
                position: relative;
            }
            .report-section-title::after {
                content: '';
                position: absolute;
                bottom: -10px;
                left: 30px;
                width: 0;
                height: 0;
                border-left: 10px solid transparent;
                border-right: 10px solid transparent;
                border-top: 10px solid #2c3e50;
            }
            @media print {
                body {
                    padding: 0;
                    background: white;
                }
                .change-box {
                    break-inside: avoid;
                    margin-bottom: 1.5rem;
                }
                .header, .metadata, .summary-section {
                    break-after: avoid;
                }
                .report-section-title {
                    break-after: avoid;
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
                # Check if change has practice groups
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
            "gpt-4o-2024-08-06": "GPT-4o (August 2024)",
            "gpt-4o-2024-05-13": "GPT-4o (May 2024)",
            "gpt-4-turbo": "GPT-4 Turbo",
            "gpt-3.5-turbo": "GPT-3.5 Turbo",
            "claude-3-opus-20240229": "Claude 3 Opus",
            "claude-3-sonnet-20240229": "Claude 3 Sonnet"
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