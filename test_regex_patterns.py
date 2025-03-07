import asyncio
import re
import sys
import os
import logging
from typing import List, Dict, Any, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('regex_test.log')
    ]
)

logger = logging.getLogger("regex_test")

# Add project root to path to enable imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the components we need to test
from src.services.bill_scraper import BillScraper

class RegexPatternTester:
    """Test regex patterns on real bill text to validate pattern matching"""

    def __init__(self, bill_text):
        self.bill_text = bill_text
        self.results = {}

    def test_pattern(self, name, pattern, flags=re.DOTALL):
        """Test a regex pattern and store the results"""
        try:
            logger.info(f"Testing pattern: '{name}'")
            matches = list(re.finditer(pattern, self.bill_text, flags))

            result = {
                "pattern": pattern,
                "matches_count": len(matches),
                "match_details": []
            }

            # Store detailed info for each match
            for i, match in enumerate(matches[:10]):  # Limit to first 10 matches
                groups = match.groups()
                group_dict = match.groupdict() if hasattr(match, 'groupdict') else {}

                match_context = self.bill_text[max(0, match.start() - 50):match.start()]
                match_text = self.bill_text[match.start():match.end()]
                after_context = self.bill_text[match.end():min(len(self.bill_text), match.end() + 50)]

                match_info = {
                    "index": i,
                    "start": match.start(),
                    "end": match.end(),
                    "text": match_text,
                    "context_before": match_context,
                    "context_after": after_context,
                    "groups": [str(g) for g in groups],
                    "named_groups": {k: str(v) for k, v in group_dict.items()}
                }

                result["match_details"].append(match_info)

            self.results[name] = result
            logger.info(f"Pattern '{name}' found {len(matches)} matches")

            return matches

        except Exception as e:
            logger.error(f"Error testing pattern '{name}': {str(e)}")
            self.results[name] = {
                "pattern": pattern,
                "error": str(e),
                "matches_count": 0,
                "match_details": []
            }
            return []

    def test_bill_section_patterns(self):
        """Test patterns specifically for bill sections"""
        # Pattern from your base_parser.py
        original_pattern = re.compile(
            r'(?:^|\n+)\s*'
            r'(?P<label>(?:SECTION|SEC)\.\s+(?P<number>\d+)\.)'
            r'\s*(?P<body>.*?)(?='
            r'(?:\n+(?:SECTION|SEC)\.\s+\d+\.|$))',
            re.DOTALL | re.IGNORECASE
        )

        # Test the original pattern
        original_matches = self.test_pattern("Original Bill Section Pattern", original_pattern.pattern, 
                                          re.DOTALL | re.IGNORECASE)

        # Test alternative patterns
        # Pattern 1: More flexible with whitespace
        alt_pattern1 = (
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.?\s*(?P<number>\d+)\.)\s*'
            r'(?P<body>(?:.+?)(?=\n\s*(?:SECTION|SEC)\.?\s*\d+\.|\Z))'
        )
        alt1_matches = self.test_pattern("Alternative Pattern 1", alt_pattern1, 
                                      re.DOTALL | re.IGNORECASE)

        # Pattern 2: More aggressive with capturing section body
        alt_pattern2 = (
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.\s+(?P<number>\d+)\.).*?(?:\n)'
            r'(?P<body>.*?)(?=\n\s*(?:SECTION|SEC)\.\s+\d+\.|\Z)'
        )
        alt2_matches = self.test_pattern("Alternative Pattern 2", alt_pattern2, 
                                      re.DOTALL | re.IGNORECASE)

        # Pattern 3: Direct matching of section headers only
        section_header_pattern = r'\n\s*((?:SECTION|SEC)\.\s+(\d+)\.)'
        header_matches = self.test_pattern("Section Headers Only", section_header_pattern, 
                                        re.IGNORECASE)

        # Get headers with simple pattern
        simple_pattern = r'(SECTION\s+\d+\.|SEC\.\s+\d+\.)'
        simple_matches = self.test_pattern("Simple Header Pattern", simple_pattern, 
                                        re.IGNORECASE)

        return {
            "original": len(original_matches),
            "alt_pattern1": len(alt1_matches),
            "alt_pattern2": len(alt2_matches),
            "header_only": len(header_matches),
            "simple_header": len(simple_matches)
        }

    def test_digest_section_patterns(self):
        """Test patterns for digest sections"""
        # Pattern from your code
        digest_pattern = r'\((\d+)\)\s+([^(]+)(?=\(\d+\)|$)'
        digest_matches = self.test_pattern("Digest Section Pattern", digest_pattern, re.DOTALL)

        # Alternative digest pattern
        alt_digest_pattern = r'\((\d+)\)\s+((?:(?!\(\d+\)).)+)'
        alt_digest_matches = self.test_pattern("Alternative Digest Pattern", alt_digest_pattern, re.DOTALL)

        return {
            "original": len(digest_matches),
            "alternative": len(alt_digest_matches)
        }

    def test_code_reference_patterns(self):
        """Test patterns for code references"""
        # Standard format: "Section 123 of the Education Code"
        pattern1 = r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        matches1 = self.test_pattern("Section X of the Y Code", pattern1)

        # Reverse format: "Education Code Section 123"
        pattern2 = r'(?i)([A-Za-z\s]+Code)\s+Section(?:s)?\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)'
        matches2 = self.test_pattern("Y Code Section X", pattern2)

        # Section header format: "Section X of the Y Code is amended/added/repealed"
        pattern3 = r'(?i)Section\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)\s+(?:is|are)'
        matches3 = self.test_pattern("Section Header Format", pattern3)

        # Range format: "Sections 123-128 of the Education Code"
        pattern4 = r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?)\s*(?:to|through|-)\s*(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        matches4 = self.test_pattern("Section Range Format", pattern4)

        # Enhanced pattern for capturing decimal points
        pattern5 = r'(?i)Section\s+(\d+\.\d+)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        matches5 = self.test_pattern("Decimal Section Numbers", pattern5)

        return {
            "standard_format": len(matches1),
            "reverse_format": len(matches2),
            "header_format": len(matches3),
            "range_format": len(matches4),
            "decimal_format": len(matches5)
        }

    def test_action_type_patterns(self):
        """Test patterns for determining action types (added, amended, repealed)"""
        # Check for action keywords in the bill sections
        actions = {
            "amended": r'(?i)\s+is\s+amended',
            "added": r'(?i)\s+is\s+added',
            "repealed": r'(?i)\s+is\s+repealed',
            "repealed_and_added": r'(?i)\s+is\s+repealed.*?is\s+added',
            "amended_and_repealed": r'(?i)\s+is\s+amended.*?is\s+repealed'
        }

        results = {}
        for action, pattern in actions.items():
            matches = self.test_pattern(f"Action Type: {action}", pattern)
            results[action] = len(matches)

        return results

    def generate_report(self):
        """Generate a detailed report of pattern testing results"""
        report = "=" * 80 + "\n"
        report += "REGEX PATTERN TESTING REPORT\n"
        report += "=" * 80 + "\n\n"

        # Bill section patterns
        bill_section_results = self.test_bill_section_patterns()
        report += "BILL SECTION PATTERNS\n"
        report += "-" * 50 + "\n"
        for pattern_name, count in bill_section_results.items():
            report += f"{pattern_name}: {count} matches\n"
        report += "\n"

        # Digest section patterns
        digest_section_results = self.test_digest_section_patterns()
        report += "DIGEST SECTION PATTERNS\n"
        report += "-" * 50 + "\n"
        for pattern_name, count in digest_section_results.items():
            report += f"{pattern_name}: {count} matches\n"
        report += "\n"

        # Code reference patterns
        code_ref_results = self.test_code_reference_patterns()
        report += "CODE REFERENCE PATTERNS\n"
        report += "-" * 50 + "\n"
        for pattern_name, count in code_ref_results.items():
            report += f"{pattern_name}: {count} matches\n"
        report += "\n"

        # Action type patterns
        action_results = self.test_action_type_patterns()
        report += "ACTION TYPE PATTERNS\n"
        report += "-" * 50 + "\n"
        for action_name, count in action_results.items():
            report += f"{action_name}: {count} matches\n"
        report += "\n"

        # Sample matches for each pattern
        report += "SAMPLE MATCHES\n"
        report += "=" * 80 + "\n"
        for pattern_name, result in self.results.items():
            report += f"\nPattern: {pattern_name}\n"
            report += f"Total Matches: {result['matches_count']}\n"
            report += "-" * 50 + "\n"

            if result['matches_count'] > 0:
                for i, match in enumerate(result['match_details'][:5]):  # Show first 5 matches
                    report += f"Match {i+1} (pos {match['start']}):\n"
                    report += f"  Context Before: ...{match['context_before']}\n"
                    report += f"  >>> MATCH: {match['text']}\n"
                    report += f"  Context After: {match['context_after']}...\n"

                    if match['named_groups']:
                        report += "  Named Groups:\n"
                        for group_name, group_text in match['named_groups'].items():
                            report += f"    {group_name}: {group_text}\n"
                    elif match['groups']:
                        report += "  Groups:\n"
                        for j, group in enumerate(match['groups']):
                            report += f"    Group {j+1}: {group}\n"

                    report += "\n"
            else:
                report += "No matches found\n\n"

        return report


async def run_regex_test(bill_number="AB114", session_year=2023):
    """
    Run the regex pattern tester on a specific bill
    """
    try:
        # Fetch the bill text
        logger.info(f"Fetching bill text for {bill_number} ({session_year})")
        scraper = BillScraper()
        bill_response = await scraper.get_bill_text(bill_number, session_year)

        if not bill_response or 'full_text' not in bill_response:
            logger.error("Failed to retrieve bill text")
            return

        bill_text = bill_response['full_text']
        logger.info(f"Successfully retrieved bill text ({len(bill_text)} characters)")

        # Save the raw bill text for reference
        with open("raw_bill_text.txt", "w", encoding="utf-8") as f:
            f.write(bill_text)
        logger.info("Saved raw bill text to 'raw_bill_text.txt'")

        # Create the regex tester and run tests
        logger.info("Starting regex pattern tests")
        tester = RegexPatternTester(bill_text)
        report = tester.generate_report()

        # Save the report
        with open("regex_test_report.txt", "w", encoding="utf-8") as f:
            f.write(report)
        logger.info("Saved regex test report to 'regex_test_report.txt'")

        # Save the detailed results as JSON
        import json
        with open("regex_test_results.json", "w", encoding="utf-8") as f:
            json.dump(tester.results, f, indent=2, default=str)
        logger.info("Saved detailed test results to 'regex_test_results.json'")

        # Print a summary
        print("\nREGEX PATTERN TEST SUMMARY")
        print("=" * 50)
        print(f"Bill: {bill_number} ({session_year})")
        print(f"Bill Text Length: {len(bill_text)} characters")
        print("\nBill Section Patterns:")
        for name, count in tester.test_bill_section_patterns().items():
            print(f"  {name}: {count} matches")

        print("\nDigest Section Patterns:")
        for name, count in tester.test_digest_section_patterns().items():
            print(f"  {name}: {count} matches")

        print("\nCheck the following files for detailed results:")
        print("- regex_test_report.txt - Full text report")
        print("- regex_test_results.json - Detailed JSON data")
        print("- raw_bill_text.txt - Raw bill text")
        print("- regex_test.log - Detailed log")

    except Exception as e:
        logger.error(f"Error during regex test: {str(e)}", exc_info=True)
        print(f"Error: {str(e)}")


if __name__ == "__main__":
    # Set up asyncio event loop handling based on platform
    if sys.platform == 'win32':
        # Windows-specific event loop policy
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Run the async test function
    asyncio.run(run_regex_test())