"""
Improved section extractor for AB114 bills.
This is a standalone script demonstrating improved section extraction logic.
"""
import re
import logging
import sys
import os
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("section_extractor")

class BillSection:
    """Simplified BillSection class for this example"""
    def __init__(self, number, label, text):
        self.number = number
        self.original_label = label
        self.text = text

def extract_ab114_sections(bill_text: str) -> List[BillSection]:
    """
    Enhanced extraction method specifically for AB114 format bills.
    Uses a multi-stage approach to find sections with the standard format:
    - SECTION 1. for the first section
    - SEC. N. for all other sections (2-124)
    
    AB114 has an unusual format where many section headers appear on isolated lines
    separated by blank lines, making them harder to detect with standard patterns.
    """
    logger.info("Using enhanced AB114 section extraction method")
    
    # Dictionary to store sections by number
    section_dict = {}
    
    # Stage 1: Find section 1 first - it's usually well-formatted and distinctive
    section1_pattern = re.compile(
        r'(?:^|\n)\s*(?:SECTION\s+1\.)',
        re.MULTILINE | re.IGNORECASE
    )
    
    section1_match = section1_pattern.search(bill_text)
    
    if section1_match:
        logger.info("Found SECTION 1.")
        
        # Extract section 1 
        section1_start = section1_match.start()
        
        # Find where section 1 ends (where section 2 begins)
        section2_pattern = re.compile(
            r'(?:^|\n)\s*(?:SEC\.|SECTION)\s+2\.',
            re.MULTILINE | re.IGNORECASE
        )
        
        section2_match = section2_pattern.search(bill_text, section1_start + 10)
        if section2_match:
            section1_end = section2_match.start()
        else:
            # If can't find section 2, take a reasonable chunk
            section1_end = min(section1_start + 5000, len(bill_text))
            
        # Extract section 1 text
        section1_text = bill_text[section1_start:section1_end].strip()
        header_end = section1_text.find('\n')
        
        if header_end != -1:
            section1_body = section1_text[header_end:].strip()
            
            # Create section 1
            section_dict[1] = BillSection(
                number="1",
                label="SECTION 1.",
                text=section1_body
            )
    
    # Stage 2: Look for isolated section markers (common in AB114)
    # This pattern specifically looks for standalone SEC. N. format
    standalone_section_pattern = re.compile(
        r'(?:^|\n)\s*((?:SEC\.|SECTION)\.\s+(\d+)\.)\s*(?:\n|$)',
        re.MULTILINE
    )
    
    standalone_matches = list(standalone_section_pattern.finditer(bill_text))
    logger.info(f"Found {len(standalone_matches)} standalone section headers")
    
    # Process standalone section matches
    for i, match in enumerate(standalone_matches):
        try:
            section_num = int(match.group(2))
            
            # Skip section 1 (we handled it separately) or if out of range
            if section_num == 1 or section_num > 124:
                continue
                
            # Skip if we already have this section
            if section_num in section_dict:
                continue
            
            # Make sure this isn't a statute reference (like "SEC. 55. of Chapter")
            context_start = max(0, match.start() - 50)
            context_end = min(len(bill_text), match.end() + 50)
            context = bill_text[context_start:context_end]
            
            if "of Chapter" in context[match.start()-context_start:match.end()-context_start+20]:
                logger.info(f"Skipping section {section_num} - appears to be a statute reference")
                continue
            
            # Extract section body - start from after the header line
            header_end = bill_text.find('\n', match.start())
            if header_end == -1:
                continue  # Skip if no newline found
            
            # Find the end of this section (next standalone section or end of text)
            section_end = len(bill_text)
            
            # Look for the next few section markers as potential endpoints
            for j in range(i+1, min(i+10, len(standalone_matches))):
                next_match = standalone_matches[j]
                next_num = int(next_match.group(2))
                
                # Only use higher section numbers as endpoints
                if next_num > section_num:
                    section_end = next_match.start()
                    break
            
            # Extract the section body
            section_body = bill_text[header_end+1:section_end].strip()
            
            # Skip if body is empty or too short
            if not section_body or len(section_body) < 30:
                continue
            
            # Create the section
            section_dict[section_num] = BillSection(
                number=str(section_num),
                label=match.group(1),
                text=section_body
            )
            logger.info(f"Added standalone section {section_num}")
        except (ValueError, IndexError):
            continue
    
    # Stage 3: Try standard SEC. N. pattern (for sections with inline content)
    inline_section_pattern = re.compile(
        r'(?:^|\n)\s*(?:SEC\.\s+(\d+)\.)\s+([^\n]+)',
        re.MULTILINE | re.IGNORECASE
    )
    
    inline_matches = list(inline_section_pattern.finditer(bill_text))
    logger.info(f"Found {len(inline_matches)} SEC. N. format sections with inline content")
    
    # Process each section match
    for i, match in enumerate(inline_matches):
        try:
            section_num = int(match.group(1))
            
            # Skip if out of range for AB114 or already found
            if section_num == 1 or section_num > 124 or section_num in section_dict:
                continue
            
            section_label = f"SEC. {section_num}."
            start_body = match.group(2)
            start_pos = match.start()
            
            # Find where this section ends (next section or end of text)
            end_pos = len(bill_text)
            
            # Look for next section markers
            next_section_pattern = re.compile(
                r'(?:^|\n)\s*(?:SEC\.|SECTION)\.\s+\d+\.',
                re.MULTILINE | re.IGNORECASE
            )
            next_match = next_section_pattern.search(bill_text, start_pos + len(match.group(0)))
            if next_match:
                end_pos = next_match.start()
            
            # Extract full section text
            full_section_text = bill_text[start_pos:end_pos].strip()
            
            # Skip header to get body
            header_end = full_section_text.find('\n')
            if header_end != -1:
                section_body = full_section_text[header_end:].strip()
                # Prepend the start_body if it's not just whitespace
                if start_body.strip():
                    section_body = start_body + '\n' + section_body
            else:
                section_body = start_body
            
            # Skip if body is too short
            if len(section_body) < 30:
                continue
            
            # Create the section
            section_dict[section_num] = BillSection(
                number=str(section_num),
                label=section_label,
                text=section_body
            )
            logger.info(f"Added inline section {section_num}")
        except (ValueError, IndexError):
            continue
    
    # Stage 4: Try direct search for specific critical section numbers
    critical_sections = [1, 2, 3, 6, 8, 10, 20, 30, 40, 50, 55, 60, 70]
    missing_critical = [num for num in critical_sections if num not in section_dict]
    
    if missing_critical:
        logger.info(f"Searching for {len(missing_critical)} missing critical sections")
        
        for section_num in missing_critical:
            # Format section markers based on section number
            if section_num == 1:
                section_markers = [f"SECTION {section_num}.", f"Section {section_num}."]
            else:
                section_markers = [f"SEC. {section_num}.", f"Sec. {section_num}."]
            
            for marker in section_markers:
                # Check that it's not a statute reference like "SEC. 55. of Chapter"
                statute_marker = marker + " of Chapter"
                if bill_text.find(statute_marker) != -1:
                    logger.info(f"Skipping section {section_num} - found as statute reference")
                    continue
                
                pos = bill_text.find(marker)
                if pos >= 0:
                    # Found this section
                    start_pos = pos
                    
                    # Find where this section ends
                    end_pos = len(bill_text)
                    
                    # Look for the next section marker
                    for next_num in range(section_num + 1, section_num + 5):
                        next_markers = [f"SEC. {next_num}.", f"Sec. {next_num}.", 
                                       f"SECTION {next_num}.", f"Section {next_num}."]
                        
                        for next_marker in next_markers:
                            next_pos = bill_text.find(next_marker, start_pos + len(marker))
                            if next_pos > 0 and next_pos < end_pos:
                                end_pos = next_pos
                                break
                    
                    # Extract the section text
                    section_text = bill_text[start_pos:end_pos].strip()
                    
                    # Split off the header line
                    header_end = section_text.find('\n')
                    if header_end != -1:
                        section_body = section_text[header_end:].strip()
                        
                        # Skip if body is empty or too short
                        if not section_body or len(section_body) < 30:
                            continue
                        
                        # Create section
                        section_dict[section_num] = BillSection(
                            number=str(section_num),
                            label=marker,
                            text=section_body
                        )
                        logger.info(f"Found critical section {section_num} with direct search")
                        break
                
                # If we found this section, stop looking for it
                if section_num in section_dict:
                    break
    
    # Stage 5: Look for more standalone section markers with different patterns
    additional_patterns = [
        # Pattern for "SEC. N." on its own line with whitespace
        re.compile(r'(?:^|\n)\s*SEC\.\s+(\d+)\.\s*$', re.MULTILINE),
        # Pattern for "Section N." format
        re.compile(r'(?:^|\n)\s*Section\s+(\d+)\.\s*$', re.MULTILINE),
        # Pattern with newlines around it
        re.compile(r'\n\s*SEC\.\s+(\d+)\.\s*\n', re.MULTILINE)
    ]
    
    for pattern_idx, pattern in enumerate(additional_patterns):
        matches = list(pattern.finditer(bill_text))
        logger.info(f"Additional pattern {pattern_idx+1} found {len(matches)} potential section markers")
        
        for match in matches:
            try:
                section_num = int(match.group(1))
                
                # Skip if already found or out of range
                if section_num in section_dict or section_num > 124 or section_num == 1:
                    continue
                
                # Skip if this looks like a statute reference
                context_start = max(0, match.start() - 50)
                context_end = min(len(bill_text), match.end() + 50)
                context = bill_text[context_start:context_end]
                
                if "of Chapter" in context or "Code" in context[:50]:
                    continue
                
                # Get content after this marker
                marker_end = match.end()
                next_marker_pattern = re.compile(r'(?:^|\n)\s*(?:SEC\.|SECTION|Section)\.\s+\d+\.', re.MULTILINE)
                next_match = next_marker_pattern.search(bill_text, marker_end)
                
                if next_match:
                    section_end = next_match.start()
                else:
                    section_end = min(marker_end + 3000, len(bill_text))
                
                # Extract body, skipping the header
                section_body = bill_text[marker_end:section_end].strip()
                
                # Skip if too short
                if len(section_body) < 30:
                    continue
                
                # Create section
                original_label = f"SEC. {section_num}."
                section_dict[section_num] = BillSection(
                    number=str(section_num),
                    label=original_label,
                    text=section_body
                )
                
                logger.info(f"Found section {section_num} with additional pattern {pattern_idx+1}")
            except (ValueError, IndexError):
                continue
    
    # Stage 6: Special search for "SEC. 55." which appears in AB114 as both
    # a bill section and a statute reference
    if 55 not in section_dict:
        # Try to find the correct SEC. 55. that's a bill section, not the statute reference
        sec55_marker = "SEC. 55."
        sec55_pos = bill_text.find(sec55_marker)
        
        if sec55_pos > 0:
            # Check the context to ensure this isn't the "SEC. 55. of Chapter" reference
            sec55_context = bill_text[sec55_pos:sec55_pos+50]
            if "of Chapter" not in sec55_context:
                # This is likely the bill section
                start_pos = sec55_pos
                
                # Find next section marker
                end_pos = len(bill_text)
                for next_num in range(56, 61):
                    next_marker = f"SEC. {next_num}."
                    next_pos = bill_text.find(next_marker, start_pos + len(sec55_marker))
                    if next_pos > 0:
                        end_pos = next_pos
                        break
                
                # Extract text
                section_text = bill_text[start_pos:end_pos].strip()
                header_end = section_text.find('\n')
                
                if header_end != -1:
                    section_body = section_text[header_end+1:].strip()
                    
                    if len(section_body) > 30:
                        section_dict[55] = BillSection(
                            number="55",
                            label="SEC. 55.",
                            text=section_body
                        )
                        logger.info("Found special case section 55")
    
    # Convert dictionary to list, filtering out None values
    sections = [section for num, section in sorted(section_dict.items()) if section is not None]
    
    # Final analysis
    found_count = len(sections)
    expected_count = 124
    
    logger.info(f"Enhanced extraction found {found_count} real bill sections out of {expected_count}")
    
    # Report on critical sections
    critical_found = [s for s in sections if s.number in ['1', '2', '3', '6', '8']]
    logger.info(f"Found {len(critical_found)}/{len(['1', '2', '3', '6', '8'])} critical sections")
    
    return sections

def main():
    """Main function to test the improved section extractor"""
    logger.info("Testing improved section extractor")
    
    test_files = ['test_output/ab114_raw.txt']
    for test_file in test_files:
        if os.path.exists(test_file):
            logger.info(f"Testing with file: {test_file}")
            with open(test_file, 'r', encoding='utf-8') as f:
                bill_text = f.read()
                
            sections = extract_ab114_sections(bill_text)
            
            # Report on results
            logger.info(f"Found {len(sections)} sections")
            
            # Show section numbers
            section_numbers = [s.number for s in sections]
            logger.info(f"Section numbers: {', '.join(section_numbers[:20])}" + 
                       ("..." if len(section_numbers) > 20 else ""))
            
            # Check section lengths
            section_lengths = [len(s.text) for s in sections]
            avg_length = sum(section_lengths) / len(section_lengths) if section_lengths else 0
            logger.info(f"Average section length: {avg_length:.1f} characters")
            
            # Check critical sections
            critical_sections = ["1", "2", "3", "6", "8"]
            found_critical = [num for num in critical_sections if num in section_numbers]
            
            if len(found_critical) == len(critical_sections):
                logger.info("SUCCESS: All critical sections found!")
            else:
                missing = [num for num in critical_sections if num not in section_numbers]
                logger.info(f"Missing critical sections: {missing}")
            
            # Save extracted sections to a file
            output_file = f"{os.path.splitext(test_file)[0]}_extracted_sections.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"Total sections extracted: {len(sections)}\n\n")
                for i, section in enumerate(sections):
                    f.write(f"SECTION {section.number}: {section.original_label}\n")
                    f.write(f"Length: {len(section.text)} characters\n")
                    f.write(f"Preview: {section.text[:100].replace(chr(10), ' ')}...\n\n")
            
            logger.info(f"Saved extracted sections to {output_file}")
        else:
            logger.error(f"Test file not found: {test_file}")

if __name__ == "__main__":
    main()