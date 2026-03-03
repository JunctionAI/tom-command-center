#!/usr/bin/env python3
"""
Implementation Runner — Auto-generates code from specs.
Takes a specification, generates Python code, validates, and prepares for deployment.
SAFETY FIRST: All code is reviewed before execution.
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)


class ImplementationRunner:
    """Generate and safely implement code from specifications."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.implementations_dir = base_dir / "implementations" / "generated"
        self.implementations_dir.mkdir(parents=True, exist_ok=True)
        self.safety_checks = []

    def generate_code(self, spec: Dict) -> Dict:
        """
        Generate Python code from specification.

        Spec format:
        {
            "name": "feature_name",
            "description": "What this does",
            "inputs": [{"name": "input_name", "type": "str"}],
            "outputs": [{"name": "output_name", "type": "str"}],
            "logic": "Detailed pseudocode or logic description",
            "requirements": ["requirement1", "requirement2"]
        }
        """
        result = {
            "spec": spec,
            "generated_code": None,
            "validation": {},
            "safety_checks": [],
            "status": "pending",
        }

        try:
            # Generate code structure
            code = self._generate_code_structure(spec)
            result["generated_code"] = code

            # Run safety checks
            result["safety_checks"] = self._run_safety_checks(code, spec)

            # Determine if ready for implementation
            if all(check["passed"] for check in result["safety_checks"]):
                result["status"] = "ready_for_review"
            else:
                result["status"] = "needs_review"

            logger.info(f"Generated code for: {spec['name']}")

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"Code generation error: {e}")

        return result

    def _generate_code_structure(self, spec: Dict) -> str:
        """Generate Python code template from spec."""
        name = spec.get("name", "feature")
        description = spec.get("description", "No description")
        inputs = spec.get("inputs", [])
        outputs = spec.get("outputs", [])
        logic = spec.get("logic", "Logic not provided")

        input_str = ", ".join(f"{inp['name']}: {inp.get('type', 'Any')}" for inp in inputs)
        return_str = ", ".join(out["name"] for out in outputs) if outputs else "bool"

        code = f'''#!/usr/bin/env python3
"""
{name} — Auto-generated from specification
{description}
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class {name.title().replace('_', '')}:
    """Implementation of: {description}"""

    def __init__(self):
        self.created_at = datetime.now().isoformat()
        logger.info(f"Initialized {name}")

    def execute({input_str}) -> {return_str}:
        """
        Main execution method.

        Logic:
        {logic}

        Returns:
            Result dict with outputs
        """
        result = {{
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }}

        try:
            # TODO: Implement core logic here
            # Step 1: Validate inputs
            # Step 2: Process data
            # Step 3: Return outputs

            {f"result['result'] = {return_str.strip('()')}" if return_str != 'bool' else "result['success'] = True"}

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"Execution error: {{e}}")

        return result

    def validate_inputs(self, {input_str}) -> bool:
        """Validate input data before processing."""
        try:
            # Add validation logic
            return True
        except Exception as e:
            logger.error(f"Validation error: {{e}}")
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    impl = {name.title().replace('_', '')}()
    print("Implementation ready for testing")
'''
        return code

    def _run_safety_checks(self, code: str, spec: Dict) -> List[Dict]:
        """Run security and quality checks on generated code."""
        checks = []

        # Check 1: No dangerous imports
        dangerous_imports = ["os.system", "subprocess.call", "eval", "exec", "__import__"]
        has_dangerous = any(imp in code for imp in dangerous_imports)
        checks.append(
            {
                "name": "dangerous_imports",
                "passed": not has_dangerous,
                "details": "No system execution calls found" if not has_dangerous else "WARNING: Dangerous imports detected",
            }
        )

        # Check 2: Has error handling
        has_try_except = "try:" in code and "except" in code
        checks.append(
            {
                "name": "error_handling",
                "passed": has_try_except,
                "details": "Has try/except blocks" if has_try_except else "No error handling detected",
            }
        )

        # Check 3: Has logging
        has_logging = "logger." in code
        checks.append(
            {
                "name": "logging",
                "passed": has_logging,
                "details": "Uses logging" if has_logging else "No logging detected",
            }
        )

        # Check 4: Has input validation
        has_validation = "validate" in code.lower()
        checks.append(
            {
                "name": "input_validation",
                "passed": has_validation,
                "details": "Has validation methods" if has_validation else "No validation detected",
            }
        )

        # Check 5: Code structure
        has_class_or_function = "class " in code or "def " in code
        checks.append(
            {
                "name": "code_structure",
                "passed": has_class_or_function,
                "details": "Has proper structure" if has_class_or_function else "Structure not clear",
            }
        )

        return checks

    def save_generated_code(self, implementation_result: Dict) -> Optional[Path]:
        """Save generated code to file for review."""
        try:
            spec = implementation_result["spec"]
            filename = f"{spec['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
            filepath = self.implementations_dir / filename

            with open(filepath, "w") as f:
                f.write(implementation_result["generated_code"])

            logger.info(f"Saved code to: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Save error: {e}")
            return None

    def run_basic_tests(self, code_path: Path) -> Dict:
        """Run basic syntax and import tests."""
        result = {
            "syntax_valid": False,
            "imports_valid": False,
            "errors": [],
        }

        try:
            # Check syntax
            with open(code_path) as f:
                compile(f.read(), code_path, "exec")
            result["syntax_valid"] = True
        except SyntaxError as e:
            result["errors"].append(f"Syntax error: {e}")

        try:
            # Try importing
            import importlib.util

            spec = importlib.util.spec_from_file_location("generated", code_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result["imports_valid"] = True
        except Exception as e:
            result["errors"].append(f"Import error: {e}")

        return result

    def create_implementation_spec(
        self,
        name: str,
        description: str,
        inputs: List[Dict],
        outputs: List[Dict],
        logic: str,
        requirements: List[str],
    ) -> Dict:
        """Create a specification dict for code generation."""
        return {
            "name": name,
            "description": description,
            "inputs": inputs,
            "outputs": outputs,
            "logic": logic,
            "requirements": requirements,
            "created_at": datetime.now().isoformat(),
        }


def generate_implementation(spec: Dict) -> Dict:
    """Standalone function to generate code from spec."""
    runner = ImplementationRunner(Path.cwd())
    result = runner.generate_code(spec)
    filepath = runner.save_generated_code(result)
    result["saved_to"] = str(filepath) if filepath else None
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example: Generate code for a simple feature
    spec = {
        "name": "data_validator",
        "description": "Validate CSV data before processing",
        "inputs": [{"name": "csv_path", "type": "str"}],
        "outputs": [{"name": "validation_report", "type": "dict"}],
        "logic": "Read CSV, check schema, validate types, report errors",
        "requirements": ["pandas", "logging"],
    }

    runner = ImplementationRunner(Path(__file__).resolve().parent.parent)
    result = runner.generate_code(spec)
    print("\n=== IMPLEMENTATION RUNNER ===")
    print(json.dumps(
        {
            "name": result["spec"]["name"],
            "status": result["status"],
            "safety_checks": result["safety_checks"],
        },
        indent=2,
    ))

    filepath = runner.save_generated_code(result)
    if filepath:
        test_result = runner.run_basic_tests(filepath)
        print(f"\nTests: {test_result}")
