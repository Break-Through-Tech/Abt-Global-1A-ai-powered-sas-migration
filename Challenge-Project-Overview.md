---

> ## Challenge Advisor: Update & Finalize Your Project Overview
>
> > 💡 **These grey text instructions are just for you, the team's Challenge Advisor; please delete them once you have completed the steps below.**
>
> We've pre-populated this Challenge Project Overview page — which is what will be shared with your Break Through Tech student team in August — using the details from your submission form. You should have received an email inviting you to join this repo as a Collaborator, enabling you to add files and make edits.
> 
> In order for your project to be finalized and assigned to a team, please:
> 1. **Review all sections below** and update or expand any content as needed, making sure to address the SME Feedback in the section immediately below. Look for square brackets to find the places below that require additional inputs from you (e.g., "About [Company / Org Name]").
> 2. **Add your dataset** to the [data folder](data) in this repo.
> 3. **Close the Issue assigned to you in this repo** to let us know that you have made your edits and the overview page is ready for final review. You can do this by going to the _Issues_ tab in the top left section of the menu above, add a comment that says "CA review complete", and click the button to Close the Issue. 
>
> If you're unfamiliar with how to edit a page like this in GitHub, check out [this tutorial](https://ubc-lib-geo.github.io/gis-workshop-waml-template/content/handson/edit-readme.html) for a quick overview (start with step 2 and only edit this page), and [this guide](https://ubc-lib-geo.github.io/gis-workshop-waml-template/content/markdown.html) on how to use Markdown to compose text.
>
>
> ❌ Remember that this is a public repo. Do NOT include: Proprietary data, PII, API keys, credentials, or anything confidential.

---

## 📋 BTT Internal Evaluation Notes
*(This section is for BTT staff and CAs only — remove before sharing with students)*

| Check   | Status | Notes                                                                   |
|---------|--------|-------------------------------------------------------------------------|
| Python Compatibility | 🟢 | The tech stack includes Python for the migration and validation, making it compatible for student use. |
| Data Readiness | 🟢  | Data is small, under 1GB, making it manageable for students without extensive cleaning. |
| Resource Check | 🟢  | Only uses free-tier tools like Google Colab, accessible for all students. |

**Student Fit Score:** 7/10  
**Technical Depth Score:** 8/10  
**Overall Recommendation:** REVISE

**Advisor Feedback Draft:**
The project presents a strong integration of practical industry challenges with technical skills applicable in real-world scenarios. However, consider simplifying aspects of the LLM integration to ensure students can effectively learn and complete the project within the timeframe. Additionally, reinforce SAS training for students less familiar with it before starting these integrations. Ensure students feel supported on both legacy understanding and Python migration techniques.

---

# AI-Powered SAS Migration

**Company / Org:** Abt Global  
**Challenge Advisor:** Sameer Desale, Sameer.Desale@abtglobal.com  
**Program:** Break Through Tech AI Studio - Fall 2026

---

## 🏢 About Abt Global

Abt Global is a leader in research, technical assistance, and evaluation in the fields of public health, education, and international development. We aim to improve the lives of people around the world through data-driven insights and innovative solutions.

---

## 🎯 The Challenge

### Project Summary
In this project, you will use SAS datasets and legacy SAS programs and large language model (LLM)-based agentic AI techniques to translate SAS code into Python, validate outputs, and generate documentation of data processing workflows. This will help our company address the challenge of efficiently migrating legacy SAS systems to modern, scalable Python-based data pipelines while reducing manual effort and errors.

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

---

## 🛠️ Suggested Approach

**ML Problem Type:** 
- Natural Language Processing (NLP)
- Large Language Models (LLMs)/ Generative AI
- Agentic AI / Workflow AutomationCode Translation and Validation
  
**Recommended Libraries:**
- [e.g., pandas, scikit-learn, TensorFlow, Hugging Face]

**Evaluation Metrics:**
- Accuracy, Completeness, Usability

---

## 📚 Resources to Get Started

The following resources will help your team understand the problem space and potential technical approaches for this project:

**Background Reading:**
- [e.g., Link to an article or blog post about the problem domain]
- [e.g., Link to an industry report or case study]

**Technical Tutorials:**
- [e.g., Link to a free tutorial on the ML technique(s) involved]
- [e.g., Link to documentation for a key library or tool]

**Code Examples:**
- [e.g., Link to a relevant GitHub repo]
- [e.g., Link to a sample implementation or starter code]

**Other:**
- [Links to any additional resources — e.g., papers, videos, podcasts, etc.]

*Feel free to explore beyond these, and share anything interesting you find with me!*

---

## 🤝 How We'll Work Together

**Official check-ins:** During our biweekly 45-minute AI Studio Lab Section meeting block (2nd and 4th week of every month)

 **Other ways to reach out to me with questions:** 
* [e.g., Your team's channel within Break Through Tech’s Discord space]
* [e.g., Email; please copy your teammates and AI Studio Coach]
* [e.g., Request a team check-in on Zoom]
* [Note: I will aim to respond within 48 hours. Please reach out to your AI Studio Coach with urgent questions.]

> 💡 **Challenge Advisor: Please update the above based on your availability and preference. If you are not able to answer questions or meet with fellows outside of the biweekly Lab Section check-ins, simply write in "N/A (only available during the official check-in times)"**

**Recommended free coding / collaboration tools**
* […]
* […]

---

## 🚀 Getting Started

1. **Review this overview document** and note any questions for our first meeting
2. **Begin reviewing the dataset** using the link above
3. **Read the GitHub Projects documentation** [here](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects)

I’m excited to work with you!

---

## ❓ Questions?

Please bring any questions to our first meeting during the week of August 24th (Break Through Tech’s Bridge to Studio - Session C). 
