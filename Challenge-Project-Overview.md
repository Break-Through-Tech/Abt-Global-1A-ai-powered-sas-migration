# AI-Powered SAS Migration

**Company / Org:** Abt Global  
**Challenge Advisor:** Anita Nti,anitanti77@gmail.com  
**AI Studio Coach:** Nagalakshmi Pulivarthi,nagalakshmi.pulivarthi@breakthroughtech.org  
**Program:** Break Through Tech AI Studio - Fall 2026

---

## 🏢 About Abt Global

Abt Global is a leader in research, technical assistance, and evaluation in the fields of public health, education, and international development. We aim to improve the lives of people around the world through data-driven insights and innovative solutions.

---

## 🎯 The Challenge

### Project Summary
In this project, you will use SAS datasets and legacy SAS programs and large language model (LLM)-based agentic AI techniques to translate SAS code into Python, validate outputs, and generate documentation of data processing workflows. This will help our company address the challenge of efficiently migrating legacy SAS systems to modern, scalable Python-based data pipelines while reducing manual effort and errors.

This project was proposed as part of the Breakthrough Tech AI Program to explore how Agentic AI and Large Language Models (LLMs) can be used to modernize legacy analytics workflows.

The objective is to build a system that automates the migration of SAS data processing pipelines to Python. The solution will translate SAS programs into Python, validate that the translated code produces equivalent results, identify discrepancies, and generate documentation describing the underlying data processing logic. The project will be evaluated using a real-world SAS pipeline consisting of four interdependent programs, including macro-based processing and analytical algorithms.

Many organizations continue to rely on SAS softwares which are costly. Migrating these systems to Python often requires significant manual effort for code translation, testing, validation, and documentation. This project explores how Agentic AI can help automate portions of that workflow while maintaining accuracy and transparency.

A successful solution could provide a reusable framework for migrating legacy SAS workflows, reducing modernization effort, preserving valuable business knowledge, and helping organizations transition to more accessible and scalable Python-based analytics platforms.

### Success Criteria
Success for this project will be measured through a combination of accuracy, completeness, and usability of the end-to-end migration system. A successful project will deliver a functional, end-to-end prototype that can reliably migrate a SAS data pipeline to Python, validate the results, and clearly explain the transformation process.

### Stretch Goals
Although the core task is already complex due to macros and algorithmic logic in the pipeline. Additional work could include improving validation, enhancing documentation, building a simple demo interface, or applying the system to more complex SAS programs if time permits.

### Project Milestones

Use these milestones to guide your work. Your team will create a **GitHub Projects board** to track tasks within each milestone.

| Month      | Milestone                 | Key Activities                                                   |
|------------|---------------------------|------------------------------------------------------------------|
| **September** | Data Exploration & Setup        | Understand SAS code structures (DATA step, PROC SQL), explore sample datasets, and build initial SAS-to-Python translation prototypes. Set up the environment for executing Python scripts and loading SAS data.       |
| **October**   | Core System Development         | Develop the main translation module, implement execution pipelines, and build validation logic (row counts, column checks, aggregates). Generate basic comparison outputs between SAS and Python results.      |
| **November**  | End-to-End Pipeline Migration  | Apply the system to a real SAS pipeline consisting of four dependent programs. The system should successfully translate, execute, validate, and document the pipeline from start to finish using the provided input dataset. Finalize outputs and prepare a demonstration of the full migration workflow.s          |

> **Note for the team:** Please create a GitHub Projects board in this repository to break these milestones into weekly tasks. Go to the **Projects** tab → **New project** → Choose **Board** → Add columns for each month.

---

## 📊 Dataset

**Name and Source:** SAS datasets and legacy programs from [https://qualitynet.cms.gov/inpatient/public-reporting/overall-ratings/software](https://qualitynet.cms.gov/inpatient/public-reporting/overall-ratings/software)  
**Format:** SAS  
**Size:** under 1gb  
**Location:** Data is accessible at the source link provided.

### Key Details
- Numerical and text data stored in SAS format, including legacy programs and datasets. 
- The public data source is available at: https://qualitynet.cms.gov/inpatient/public-reporting/overall-ratings/software
- No known limitations or preprocessing needed at this time.
- [Link to data dictionary or documentation, if available]
  
### Data Exploration :
  
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

- SAS Programs for migrating to python
   - 0 – Data and Measure Standardization_2025Jul.sas
   - 1 – First Stage_Simple Average of Measure Scores_2025Jul.sas
   - 2 – Second Stage Weighted Average and Categorize Star_2025Jul.sas
   - Star_Macros.sas
- Input data sets
   - alldata_2025jul.csv
   - alldata_2025jul.sas7bdat
- SAS Program Log File
  - SAS_Log.log

- Output Datasets
  - SAS Output data files
     - less100_measure.sas7bdat, measure_average_stddev_2025jul.sas7bdat, national_average_2025jul.sas7bdat,
      outcome_mortality.sas7bdat, outcome_readmission.sas7bdat, outcome_safety.sas7bdat, process.sas7bdat
      ptexp.sas7bdat, star_2025jul.sas7bdat, std_data_2025jul_analysis.sas7bdat
  - CSV Output data files
      - less100_measure.csv, measure_average_stddev_2025jul.csv, national_average_2025jul.csv, outcome_mortality.csv
        outcome_readmission.csv, outcome_safety.csv, process.csv, ptexp.csv, star_2025jul.csv, std_data_2025jul_analysis.csv

---

## 🛠️ Suggested Approach

**ML Problem Type:** 
- Natural Language Processing (NLP)
- Large Language Models (LLMs)/ Generative AI
- Agentic AI / Workflow AutomationCode Translation and Validation
  
**Recommended Libraries:**  
     pandas, scikit-learn, pyreadstat,numpy,scipy,statsmodels,pytest,datacompy,langchain/langgrapgh,pydantic,streamlit,Docker,markdown
  
 **Models and Techniques:**   
   - Pre-trained Large Language Models (LLMs) for code understanding, code generation, and documentation.     
   - Agent-based workflow orchestration to coordinate translation, validation, debugging, and documentation tasks.     
   - Rule-based and programmatic validation techniques to compare SAS and Python outputs.  

**Input Features:**  
   - SAS source code, including DATA steps, PROC SQL statements, and macro logic.  
   - Input datasets and intermediate outputs generated throughout the SAS pipeline.  
   - Validation metrics such as row counts, column statistics, and aggregate measures.  

**Evaluation Metrics:**
- Accuracy, Completeness, Usability
- Compare translated Python outputs against SAS-generated outputs (ground truth).
- Measure correctness using:

   - Row count agreement      
    
   - Column-level value comparisons        
    
   - Aggregate statistic comparisons   
        
   - Successful execution of the end-to-end pipeline

- Evaluate the quality of generated documentation by verifying that it accurately describes the underlying data processing workflow.

---

## 📚 Resources to Get Started

The primary resources for this project are the provided SAS programs, datasets, logs, and reference outputs. These should be reviewed first so that the team understands the existing SAS workflow before designing the migration system.

**Background Reading:**
Teams may find it useful to review documentation and tutorials covering:
  - SAS DATA step concepts
	- SAS PROC SQL
	- SAS macros and macro variables
	- Reading SAS datasets with Python
	- pandas data manipulation
	- scikit-learn clustering, particularly k-means
	- LLM-based code generation and translation
	- Agentic AI workflow design
	- Automated software testing and data validation
  - LLM-generated technical documentation


*Feel free to explore beyond these, and share anything interesting you find with me!*

---

## 🤝 How We'll Work Together

**Official check-ins:** During our biweekly 45-minute AI Studio Lab Section meeting block (2nd and 4th week of every month)

During these meetings, we can:
	• Review the team’s progress against project milestones.
	• Discuss technical questions or blockers.
	• Review design and architecture decisions.
	• Discuss validation results and discrepancies.
	• Prioritize next steps.

 **Other ways to reach out to me with questions:** 
Outside of the official check-ins, please use the team’s designated Break Through Tech communication channel for project-related questions.
When asking technical questions, please include enough context for me to understand the issue—for example, the relevant SAS/Python code, error message, validation result, or GitHub issue.
For questions that affect the whole team, please use a shared communication channel rather than individual messages whenever possible so that everyone has access to the same information.
I will aim to respond to project-related questions within 48 hours when possible. For urgent program-related questions or issues requiring immediate attention, please reach out to your AI Studio Coach.


---

## 🚀 Getting Started

1. **Review this overview document** and note any questions for our first meeting
2. **Begin reviewing the dataset** using the link above
3. **Read the GitHub Projects documentation** [here](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects)

I’m excited to work with you!

---

## ❓ Questions?

Please bring any questions to our first meeting during the week of August 24th (Break Through Tech’s Bridge to Studio - Session C). 
