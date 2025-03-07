#!/usr/bin/env python
"""
Run all parser tests and generate a combined report
"""
import os
import sys
import subprocess
import logging
import argparse
from datetime import datetime
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('test_suite.log')
    ]
)

logger = logging.getLogger("test_suite")

def run_test(script_name, bill_number, session_year):
    """Run a single test script with the specified bill"""
    logger.info(f"Running {script_name} for {bill_number} ({session_year})")

    # Create command with proper arguments
    cmd = [sys.executable, script_name]

    # Prepare environment variables
    env = os.environ.copy()
    env["BILL_NUMBER"] = bill_number
    env["SESSION_YEAR"] = str(session_year)

    # Create output directory for this test
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"test_results/{bill_number}_{session_year}_{timestamp}/{os.path.basename(script_name).split('.')[0]}"
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Run the test script
        result = subprocess.run(
            cmd, 
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False  # Don't raise exception on non-zero exit
        )

        # Save stdout and stderr
        with open(f"{output_dir}/stdout.txt", "w", encoding="utf-8") as f:
            f.write(result.stdout)

        with open(f"{output_dir}/stderr.txt", "w", encoding="utf-8") as f:
            f.write(result.stderr)

        # Copy any generated files to the output directory
        for filename in [
            "parser_test_report.txt",
            "parser_verbose.log",
            "verbose_report.txt",
            "regex_test_report.txt",
            "regex_test_results.json",
            "raw_bill_text.txt"
        ]:
            if os.path.exists(filename):
                shutil.copy2(filename, f"{output_dir}/{filename}")
                # Remove the original file to avoid conflicts with next test
                os.remove(filename)

        logger.info(f"Test {script_name} completed with exit code {result.returncode}")
        return result.returncode == 0, output_dir

    except Exception as e:
        logger.error(f"Error running {script_name}: {str(e)}")
        return False, output_dir

def run_all_tests(bill_number, session_year):
    """Run all test scripts and generate a combined report"""
    logger.info(f"Starting test suite for {bill_number} ({session_year})")

    # List of test scripts to run
    test_scripts = [
        "test_base_parser.py",
        "test_parser_verbose.py",
        "test_regex_patterns.py"
    ]

    # Track results
    results = []

    # Run each test
    for script in test_scripts:
        success, output_dir = run_test(script, bill_number, session_year)
        results.append({
            "script": script,
            "success": success,
            "output_dir": output_dir
        })

    # Generate summary report
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = f"""
===============================================================================
PARSER TEST SUITE SUMMARY
===============================================================================
Bill: {bill_number} ({session_year}-{session_year+1})
Test Run: {timestamp}

"""

    # Add results for each test
    for result in results:
        status = "SUCCESS" if result["success"] else "FAILURE"
        report += f"{result['script']}: {status}\n"
        report += f"  Results in: {result['output_dir']}\n\n"

    report += "===============================================================================\n"

    # Print and save the report
    print(report)
    report_path = f"test_results/{bill_number}_{session_year}_{datetime.now().strftime('%Y%m%d_%H%M%S')}/summary_report.txt"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"Test suite completed. Summary report saved to {report_path}")
    return report_path, results

def main():
    """Main function to parse arguments and run tests"""
    parser = argparse.ArgumentParser(description="Run parser test suite")
    parser.add_argument("--bill", "-b", default="AB114", help="Bill number to test with")
    parser.add_argument("--year", "-y", type=int, default=2023, help="Session year")

    args = parser.parse_args()

    # Create test_results directory
    os.makedirs("test_results", exist_ok=True)

    # Run all tests
    report_path, results = run_all_tests(args.bill, args.year)
    print(f"\nTest suite complete. Summary report saved to {report_path}")

    # Return overall success/failure for CI/CD
    all_success = all(result["success"] for result in results)
    return 0 if all_success else 1

if __name__ == "__main__":
    sys.exit(main())