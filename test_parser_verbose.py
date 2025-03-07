import asyncio
import logging
import os
import sys
import re
import textwrap
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.style import Style
from rich.markup import escape

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Use DEBUG level for more verbose output
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('parser_verbose.log')
    ]
)

logger = logging.getLogger("parser_verbose")

# Add project root to path to enable imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the components we need to test
from src.services.bill_scraper import BillScraper
from src.services.base_parser import BaseParser

# Initialize rich console for pretty output
console = Console()

def highlight_text(text, patterns, print_to_console=True):
    """
    Create a visual representation of the text with the matched patterns highlighted.
    """
    # Create a copy of the text with escape characters
    display_text = escape(text)
    original_text = text

    # Save ranges to highlight
    highlights = []

    # For each pattern, find all matches and save their positions
    for label, pattern in patterns.items():
        for match in re.finditer(pattern, original_text, re.IGNORECASE | re.DOTALL):
            start, end = match.span()
            highlights.append((start, end, label))

    # Sort highlights by start position (in reverse so we can insert markers without affecting positions)
    highlights.sort(reverse=True)

    # Insert highlighting markers
    for start, end, label in highlights:
        color = "green" if "SECTION" in label else "blue"
        display_text = f"{display_text[:start]}[bold {color}]{display_text[start:end]}[/bold {color}]{display_text[end:]}"

    # Create a panel with the highlighted text
    panel = Panel(display_text, title=f"Text with Highlighted Patterns", expand=False)

    if print_to_console:
        console.print(panel)

    return panel

def create_section_visualization(bill_text, sections, section_type="Bill"):
    """
    Create a visual representation of where sections are found in the bill text.
    """
    # Create markers for section positions
    text_length = len(bill_text)
    markers = [' ' for _ in range(text_length)]

    section_positions = []

    for section in sections:
        section_text = section.original_label if hasattr(section, 'original_label') else f"Section {section.number}"
        section_pattern = re.escape(section_text)

        for match in re.finditer(section_pattern, bill_text, re.IGNORECASE):
            start, end = match.span()
            section_positions.append((start, section.number))

            # Mark the position in the text
            for i in range(start, min(end, text_length)):
                markers[i] = '▓'

    # Create a visual representation of the bill text with markers
    chunk_size = 100
    visualization = []

    for i in range(0, text_length, chunk_size):
        text_chunk = bill_text[i:i+chunk_size]
        marker_chunk = ''.join(markers[i:i+chunk_size])

        # Add section numbers at their positions
        annotated_markers = list(marker_chunk)
        for pos, section_num in section_positions:
            if i <= pos < i + chunk_size:
                rel_pos = pos - i
                annotated_markers[rel_pos] = section_num[0] if len(section_num) > 0 else 'X'

        visualization.append(f"{i:8d}: {text_chunk}")
        visualization.append(f"{'':8s}  {''.join(annotated_markers)}")
        visualization.append("")

    console.print(Panel('\n'.join(visualization[:30]), title=f"{section_type} Section Visualization (first 3000 chars)"))

async def test_parser_verbose():
    """
    Test the BaseParser with AB114 from 2023-2024 session with enhanced diagnostics
    """
    # Set the bill info
    bill_number = "AB114"
    session_year = 2023  # For 2023-2024 session

    console.rule(f"[bold green]Verbose Parser Test: {bill_number} ({session_year}-{session_year+1})")

    try:
        # 1. Fetch the bill text
        console.print(f"[bold]Fetching bill text...[/bold]")
        scraper = BillScraper()
        bill_response = await scraper.get_bill_text(bill_number, session_year)

        if not bill_response or 'full_text' not in bill_response:
            console.print("[bold red]Failed to retrieve bill text[/bold red]")
            return

        bill_text = bill_response['full_text']
        console.print(f"[green]Successfully retrieved bill text[/green] ({len(bill_text)} characters)")

        # Save the raw bill text for reference
        with open("raw_bill_text.txt", "w", encoding="utf-8") as f:
            f.write(bill_text)

        # Analyze bill text patterns
        console.print("\n[bold]Analyzing bill text patterns...[/bold]")

        # Check for section patterns in the text
        section_patterns = {
            "SECTION X.": r'(?:^|\n)\s*(SECTION\s+\d+\.)',
            "SEC. X.": r'(?:^|\n)\s*(SEC\.\s+\d+\.)'
        }

        # Count pattern occurrences
        pattern_counts = {}
        for name, pattern in section_patterns.items():
            matches = list(re.finditer(pattern, bill_text, re.IGNORECASE | re.DOTALL))
            pattern_counts[name] = len(matches)
            if matches:
                console.print(f"  [green]Found {len(matches)} occurrences of '{name}' pattern[/green]")
                # Print a few examples
                for i, match in enumerate(matches[:3]):
                    console.print(f"    Example {i+1}: '{match.group(0).strip()}'")
            else:
                console.print(f"  [red]No occurrences of '{name}' pattern found[/red]")

        # Highlight sample text with the patterns
        console.print("\n[bold]Sample of bill text with section headers highlighted:[/bold]")
        sample_start = bill_text.find("SECTION 1") 
        if sample_start == -1:
            sample_start = bill_text.find("SEC. 1")

        if sample_start == -1:
            sample_start = 0

        sample_text = bill_text[sample_start:sample_start+1000]
        highlight_text(sample_text, section_patterns)

        # 2. Parse the bill with detailed logging
        console.print("\n[bold]Parsing bill with BaseParser...[/bold]")
        parser = BaseParser()

        # Hook into the parser's _parse_bill_sections method for detailed diagnostics
        original_parse_bill_sections = parser._parse_bill_sections

        def detailed_parse_bill_sections(bill_portion):
            console.print("[yellow]Inside _parse_bill_sections[/yellow]")
            console.print(f"Bill portion length: {len(bill_portion)}")
            console.print(f"First 100 chars: {bill_portion[:100]}")

            # Check for section patterns in the bill portion
            for name, pattern in section_patterns.items():
                matches = list(re.finditer(pattern, bill_portion, re.IGNORECASE | re.DOTALL))
                if matches:
                    console.print(f"  [green]Found {len(matches)} '{name}' patterns in bill portion[/green]")
                else:
                    console.print(f"  [red]No '{name}' patterns found in bill portion[/red]")

            # Call the original method
            result = original_parse_bill_sections(bill_portion)
            console.print(f"Method found {len(result)} bill sections")
            return result

        # Replace the method temporarily
        parser._parse_bill_sections = detailed_parse_bill_sections

        # Now parse the bill
        parsed_bill = parser.parse_bill(bill_text)

        # 3. Report on the parsing results
        console.print("\n[bold green]Parsing complete.[/bold green] Generating visual report...")

        # Create tables for the results
        digest_table = Table(title=f"Digest Sections ({len(parsed_bill.digest_sections)})")
        digest_table.add_column("Number", style="cyan")
        digest_table.add_column("Text Preview", style="green")
        digest_table.add_column("Code References", style="yellow")
        digest_table.add_column("Bill Sections", style="magenta")

        for section in parsed_bill.digest_sections:
            text_preview = textwrap.shorten(section.text, width=60, placeholder="...")
            code_refs = ", ".join([f"{ref.code_name} {ref.section}" for ref in section.code_references])
            bill_secs = ", ".join(section.bill_sections) if section.bill_sections else "None"

            digest_table.add_row(
                section.number,
                text_preview,
                code_refs,
                bill_secs
            )

        console.print(digest_table)

        bill_table = Table(title=f"Bill Sections ({len(parsed_bill.bill_sections)})")
        bill_table.add_column("Number", style="cyan")
        bill_table.add_column("Original Label", style="blue")
        bill_table.add_column("Text Preview", style="green")
        bill_table.add_column("Code References", style="yellow")
        bill_table.add_column("Digest Reference", style="magenta")

        for section in parsed_bill.bill_sections:
            text_preview = textwrap.shorten(section.text, width=60, placeholder="...")
            code_refs = ", ".join([f"{ref.code_name} {ref.section}" for ref in section.code_references])
            digest_ref = section.digest_reference if section.digest_reference else "None"

            bill_table.add_row(
                section.number,
                section.original_label,
                text_preview,
                code_refs,
                digest_ref
            )

        console.print(bill_table)

        # Visualize where sections are in the text
        console.print("\n[bold]Section positions in bill text:[/bold]")
        create_section_visualization(bill_text, parsed_bill.bill_sections)

        # Generate section matching visualization
        console.print("\n[bold]Section Matching Summary:[/bold]")
        matched_digest = sum(1 for s in parsed_bill.digest_sections if s.bill_sections)
        matched_bill = sum(1 for s in parsed_bill.bill_sections if s.digest_reference)

        match_table = Table(title="Section Matching Results")
        match_table.add_column("Metric", style="cyan")
        match_table.add_column("Count", style="green")
        match_table.add_column("Percentage", style="yellow")

        match_table.add_row(
            "Digest Sections with Bill Section Matches",
            f"{matched_digest}/{len(parsed_bill.digest_sections)}",
            f"{matched_digest/len(parsed_bill.digest_sections)*100:.1f}%" if parsed_bill.digest_sections else "N/A"
        )

        match_table.add_row(
            "Bill Sections with Digest Reference",
            f"{matched_bill}/{len(parsed_bill.bill_sections)}",
            f"{matched_bill/len(parsed_bill.bill_sections)*100:.1f}%" if parsed_bill.bill_sections else "N/A"
        )

        console.print(match_table)

        # Output a structured report to a file
        report = {
            "bill_info": {
                "bill_number": parsed_bill.bill_number,
                "chapter_number": parsed_bill.chapter_number,
                "date_approved": str(parsed_bill.date_approved) if parsed_bill.date_approved else None,
                "date_filed": str(parsed_bill.date_filed) if parsed_bill.date_filed else None,
            },
            "parsing_results": {
                "digest_sections": len(parsed_bill.digest_sections),
                "bill_sections": len(parsed_bill.bill_sections),
                "matched_digest": matched_digest,
                "matched_bill": matched_bill
            },
            "pattern_counts": pattern_counts,
            "digest_sections": [
                {
                    "number": section.number,
                    "text_preview": section.text[:100],
                    "code_references": [f"{ref.code_name} {ref.section}" for ref in section.code_references],
                    "bill_sections": section.bill_sections
                }
                for section in parsed_bill.digest_sections
            ],
            "bill_sections": [
                {
                    "number": section.number,
                    "original_label": section.original_label,
                    "text_preview": section.text[:100],
                    "code_references": [f"{ref.code_name} {ref.section}" for ref in section.code_references],
                    "digest_reference": section.digest_reference
                }
                for section in parsed_bill.bill_sections
            ]
        }

        with open("verbose_report.txt", "w", encoding="utf-8") as f:
            import json
            json.dump(report, f, indent=2)

        console.print("\n[bold green]Verbose test completed successfully[/bold green]")
        console.print("Verbose report saved to 'verbose_report.txt'")
        console.print("Raw bill text saved to 'raw_bill_text.txt'")
        console.print("Log saved to 'parser_verbose.log'")

    except Exception as e:
        logger.error(f"Error during parser test: {str(e)}", exc_info=True)
        console.print(f"[bold red]Error:[/bold red] {str(e)}")

if __name__ == "__main__":
    # Install rich if not already installed
    try:
        import rich
    except ImportError:
        console.print("[yellow]Installing rich package for pretty output...[/yellow]")
        os.system(f"{sys.executable} -m pip install rich")
        console.print("[green]Rich installed successfully[/green]")

    # Set up asyncio event loop handling based on platform
    if sys.platform == 'win32':
        # Windows-specific event loop policy
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Run the async test function
    asyncio.run(test_parser_verbose())