# Abt Global - AI-Powered SAS Migration

---

### 👥 **Team Members**

**AI Coach:** Aram Ramos

---

## 🎯 **Project Highlights**

- Developed an Agentic AI system that automates the migration of legacy SAS workflows to Python through code translation, validation, and documentation.
- Built an end-to-end framework that translates SAS programs, compares SAS and Python outputs, and identifies discrepancies to improve migration accuracy.
- Generated automated documentation of SAS data processing logic, helping preserve business knowledge and accelerate modernization efforts.

---

## 🏗️ Project Overview

This project was proposed as part of the Breakthrough Tech AI Program to explore how Agentic AI and Large Language Models (LLMs) can be used to modernize legacy analytics workflows.

The objective is to build a system that automates the migration of SAS data processing pipelines to Python. The solution will translate SAS programs into Python, validate that the translated code produces equivalent results, identify discrepancies, and generate documentation describing the underlying data processing logic. The project will be evaluated using a real-world SAS pipeline consisting of four interdependent programs, including macro-based processing and analytical algorithms.

Many organizations continue to rely on SAS softwares which are costly. Migrating these systems to Python often requires significant manual effort for code translation, testing, validation, and documentation. This project explores how Agentic AI can help automate portions of that workflow while maintaining accuracy and transparency.

A successful solution could provide a reusable framework for migrating legacy SAS workflows, reducing modernization effort, preserving valuable business knowledge, and helping organizations transition to more accessible and scalable Python-based analytics platforms.

---

## 📊 **Data Exploration**

Overall Hospital Quality Star Rating Statistical Analysis System SAS package is used to produce the 
Centers for Medicare & Medicaid Services’ (CMS’s) Overall Hospital Quality Star Rating 
published to Care Compare on Medicare.gov This SAS Pack comprises three main SAS programs and 
one macro file to provide a specified quarter’s group scores, summary scores, and 
star ratings using a simple average of measure scores into group scores, 
a weighted average of group scores into a summary score, and k-means clustering.

The SAS programs and log files can be read by any text reader. SAS datasets can only be opened in SAS environment, or 
can be imported in python using python packages. Since it won't be possible to run the SAS programs outside of SAS 
environment, we have provided all the input and output SAS data files in CSV format along with the SAS log file and HTML
with print out from SAS procedures.

* SAS Programs for migrating to python
  - 0 – Data and Measure Standardization_2025Jul.sas
  - 1 – First Stage_Simple Average of Measure Scores_2025Jul.sas
  - 2 – Second Stage Weighted Average and Categorize Star_2025Jul.sas
  - Star_Macros.sas
* Input data sets
  - alldata_2025jul.csv
  - alldata_2025jul.sas7bdat
* SAS Program Log File
  - SAS_Log.log
* Output Datasets
  - SAS Output data files
    - less100_measure.sas7bdat, measure_average_stddev_2025jul.sas7bdat, national_average_2025jul.sas7bdat,
      outcome_mortality.sas7bdat, outcome_readmission.sas7bdat, outcome_safety.sas7bdat, process.sas7bdat
      ptexp.sas7bdat, star_2025jul.sas7bdat, std_data_2025jul_analysis.sas7bdat 
  - CSV Output data files
    - less100_measure.csv, measure_average_stddev_2025jul.csv, national_average_2025jul.csv, outcome_mortality.csv
      outcome_readmission.csv, outcome_safety.csv, process.csv, ptexp.csv, star_2025jul.csv, std_data_2025jul_analysis.csv
    
## 🧠 Model Development

This project leverages pre-trained Large Language Models (LLMs) within an Agentic AI workflow to automate SAS-to-Python migration.

### Models and Techniques
- Pre-trained Large Language Models (LLMs) for code understanding, code generation, and documentation.
- Agent-based workflow orchestration to coordinate translation, validation, debugging, and documentation tasks.
- Rule-based and programmatic validation techniques to compare SAS and Python outputs.

### Input Features
- SAS source code, including DATA steps, PROC SQL statements, and macro logic.
- Input datasets and intermediate outputs generated throughout the SAS pipeline.
- Validation metrics such as row counts, column statistics, and aggregate measures.

---

## 📈 **Results & Key Findings**

### Evaluation Strategy
- Compare translated Python outputs against SAS-generated outputs (ground truth).
- Measure correctness using:
  - Row count agreement
  - Column-level value comparisons
  - Aggregate statistic comparisons
  - Successful execution of the end-to-end pipeline
- Evaluate the quality of generated documentation by verifying that it accurately describes the underlying data processing workflow.

### Success Criteria
- Successful translation and execution of a multi-program SAS pipeline.
- Python outputs closely match SAS outputs with minimal unexplained discrepancies.
- Automated generation of meaningful documentation describing data transformations, processing steps, and analytical procedures.

---

## 📄 **References** (Optional but encouraged)

Cite relevant papers, articles, or resources that supported your project.

---

## 🙏 **Acknowledgements** (Optional but encouraged)

Thank your Challenge Advisor, host company representatives, TA, and others who supported your project.
