# Setting up python environment

- Create virtual environment: python -m venv venv

- Activate it: venv\Scripts\activate

- To install from requirements.txt: pip install -r requirements.txt

# Tests 

- python -m pytest tests/test_schema.py -v

- python -m pytest tests/test_hash_chain.py -v

- python -m pytest tests/test_triggers.py -v

- python -m pytest tests/test_tamper_detection.py -v

- python -m pytest tests/test_benchmark_results.py -v

- python -m pytest tests/test_analyze_results.py -v