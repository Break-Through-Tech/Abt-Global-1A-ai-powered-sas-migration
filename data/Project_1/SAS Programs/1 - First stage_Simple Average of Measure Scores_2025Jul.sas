*Note: it takes less than 5 minutes to run this program;
*****************************************************************;
* FIRST STAGE - 											    *;
* DERIVING GROUP SCORE FOR EACH MEASURE TYPE GROUP 			    *;
*														        *;
* SAS 9.4 WIN			   									    *;
*                        									    *;
* YALE CORE 								                    *;
* 															    *;
* For questions, please submit an inquiry to 					*;
* the QualityNet Question & Answer Tool at:						*;
* https://cmsqualitysupport.service-now.com/qnet_qa				*; 
*****************************************************************;

/*This program is used to calulate the 5 groups(domains) scores for 
  each hospital. 
  The 5 groups(domains) are:
  (1)Mortality  
  (2)Safety of Care
  (3)Readmission 
  (4)Patient Experience 
  (5)Timely and Effective Care
  The 5 groups(domains) scores of each hospitals will be used in program 2 
  to derive the hospital star ratings. 
*/

******************************************
* Outcomes - Mortality 					 *
******************************************;
*option mprint;
/* count number of measures in Outcome Mortality Group */
PROC SQL;
	select count(measure_in_name)
	into: measure_OM_cnt /*number of measures in this domain*/
	from Outcomes_mortality;/*Outcomes_mortality is generated from the SAS program '0 - Data and Measure Standardization_2025Jul'*/
QUIT;


/*OM is used to define the data name for mortality Group; 
&measure_OM is the measures in Mortality Group;
&measure_OM_cnt is the number of measures in this Group;*/
/*output group score in R.Outcome_mortality*/
%grp_score(&MEASURE_ANALYSIS, OM, &measure_OM, &measure_OM_cnt,R.Outcome_mortality);


***************************************
* Outcomes - Safety of Care			  *
***************************************;

/* count number of measures in Outcome Safety Group */
PROC SQL;
	select count(measure_in_name)
	into: measure_OS_cnt
	from Outcomes_safety;/*Outcomes_safety is generated from the SAS program '0 - Data and Measure Standardization_2025Jul'*/
QUIT;

/*OS is used to define the data name for Safety Group; 
&measure_OS is the measures in Safety Group;
&measure_OS_cnt is the number of measures in Safety Group;*/
/*output group score in R.Outcome_safety */
%grp_score(&MEASURE_ANALYSIS, OS, &measure_OS,  &measure_OS_cnt, R.Outcome_safety);


********************************************
* Outcomes - Readmission 				   *
********************************************;

/* count number of measures in Outcome Readmission Group */
PROC SQL;
	select count(measure_in_name)
	into: measure_OR_cnt
	from Outcomes_readmission;/*Outcomes_readmission is generated from the SAS program '0 - Data and Measure Standardization_2025Jul'*/
QUIT;


/*OR is used to define the data name for Readmission Group; 
&measure_OR is the measures in Readmission Group;
&measure_OR_cnt is the number of measures in Readmission Group;*/
/*output group score in R.Outcome_readmission*/
%grp_score(&MEASURE_ANALYSIS, OR, &measure_OR, &measure_OR_cnt, R.Outcome_readmission);************;




******************************************
*  Patient Experience  					 *
******************************************;

/* count number of measures in Patient Experience Group */
PROC SQL;
	select count(measure_in_name)
	into: measure_PtExp_cnt
	from Ptexp;/*Ptexp is generated from the SAS program '0 - Data and Measure Standardization_2025Jul'*/
QUIT;


/*PtExp is used to define the data name for Patient Experience Group; 
&measure_PtExp is the measures in Patient Experience Group;
&measure_PtExp_cnt is the number of measures in Patient Experience Group;*/
/*output group score in R.PtExp*/
%grp_score(&MEASURE_ANALYSIS, PtExp, &measure_PtExp,  &measure_PtExp_cnt,R.PtExp);



**********************************************
* Timely and Effective Care                  *
**********************************************;

/* count number of measures in Timely and Effective Care */
PROC SQL;
	select count(measure_in_name)
	into: measure_Process_cnt
	from Process;/*Process is generated from the SAS program '0 - Data and Measure Standardization_2025Jul'*/
QUIT;


/*Process is used to define the data name for Timely and Effective Care group; 
&measure_Process is the measures in Timely and Effective Care Group;
&measure_Process_cnt is the number of measures in Timely and Effective Care;*/
/*output group score in R.Process*/
%grp_score(&MEASURE_ANALYSIS, Process, &measure_Process,  &measure_Process_cnt, R.Process);





/*Continue to "2 - Second Stage_Weighted Average and Categorize Star_2025Jul" SAS progam*/
