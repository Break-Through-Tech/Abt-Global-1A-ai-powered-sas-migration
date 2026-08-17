*Note: it takes less than 5 minutes to run this program;
*****************************************************;
* Create Star analysis data file 			  		*;
*											  		*;
* SAS 9.4 WIN			   					  		*;
*											  		*;
* YALE CORE 	  		                      		*;
*											  		*;
* For questions, please submit an inquiry to 		*;
* the QualityNet Question & Answer Tool at:			*;
* https://cmsqualitysupport.service-now.com/qnet_qa	*; 
*****************************************************;

/*This file is used to derive analysis data 'Std_data_2025Jul_analysis', which will be used in programs 1 and 2*/
%LET PATH1=G:\breakthrough\Starrating; /* For 2025 Jul released data, MUST BE CHANGED */
%LET PATH2=G:\breakthrough\SAS output;/* For derived data sets, MUST BE CHANGED */
%LET PATH3=G:\breakthrough\SAS pack;  /* For SAS macros , MUST BE CHANGED  */

LIBNAME HC "&PATH1";
LIBNAME R "&PATH2";

%INCLUDE "&path3.\Star_Macros.sas";/*calling macros*/

%LET year = 2025;
%LET quarter = Jul;

%LET MEASURE_MEAN=R.measure_average_stddev_&year.&quarter; /*mean and standard deviation of the original measure scores*/
%LET MEASURE_ANALYSIS=R.Std_data_&year.&quarter._analysis; /* derived final analysis file */
%LET RESULTS=R.Star_&year.&quarter; /* derive hospital-level Star file */
%LET NATIONAL_MEAN=R.national_average_&year.&quarter; /* derived national average group and summary scores results */


/*proc contents data=HC.Alldata_&year.&quarter.;run;*/

/* measures on Hospital Compare in 2025Jul, after excluding re_tired measures, no_directional measures, 
	structural measures, and voluntary measures. */
%LET measure_all = MORT_30_AMI MORT_30_CABG	MORT_30_COPD MORT_30_HF	MORT_30_PN	MORT_30_STK	PSI_4_SURG_COMP	
COMP_HIP_KNEE HAI_1-HAI_6 PSI_90_SAFETY	
EDAC_30_AMI EDAC_30_HF EDAC_30_PN OP_32 READM_30_CABG READM_30_COPD READM_30_HIP_KNEE READM_30_HOSP_WIDE OP_35_ADM OP_35_ED OP_36	
H_COMP_1_STAR_RATING H_COMP_2_STAR_RATING H_COMP_3_STAR_RATING H_COMP_5_STAR_RATING H_COMP_6_STAR_RATING H_COMP_7_STAR_RATING H_GLOB_STAR_RATING H_INDI_STAR_RATING  
HCP_COVID_19 IMM_3 OP_10 OP_13  OP_18b /*OP_2*/ OP_22 OP_23 OP_29 /*OP_3b*/ OP_8  PC_01 SAFE_USE_OF_OPIOIDS SEP_1;
*OP_2 and OP_3b are removed for year 2025;*SAFE_USE_OF_OPIOIDS is added for year 2025;


************************************************************************
* APPLY THE FOLLOWING EXCLUSION CRITERIA:                              *
* MEASURE VOLUME <=100                                                 *
************************************************************************;

DATA All_data_&year.&quarter ;
	set HC.Alldata_&year.&quarter.;
run;


PROC TABULATE DATA=All_data_&year.&quarter out=measure_volume0; 
	var &measure_all;

	table n*(&measure_all);
RUN;

PROC TRANSPOSE data=Measure_volume0 out=measure_volume_t0;
RUN;

DATA include_measure0  (drop=_NAME_ _LABEL_ rename = (COL1=freq)); 
	SET measure_volume_t0;

	if _name_ ^= '_PAGE_'  and _name_^='_TABLE_';
	measure_in_name = tranwrd(_NAME_, '_N', '');

	measure_in_std = 'std_'||trim(measure_in_name);

RUN;

PROC SQL;
	select measure_in_name into: measure_in separated by '' notrim
	from include_measure0;
QUIT;
%put &measure_in;


/* &measure_cnt: number of included measure */
PROC SQL;
	select count(measure_in_name)
	into: measure_cnt
	from include_measure0;
QUIT;
%put &measure_cnt;


/*COUNT # HOSPITALS PER MEASURE FOR ALL MEASURES*/
PROC TABULATE DATA=All_data_&year.&quarter out=measure_volume; 
	var &measure_all;

	table n*(&measure_all);
RUN;

PROC TRANSPOSE data=Measure_volume out=measure_volume_t;
RUN;

/* IDENTIFY MEASURES WITH VOLUMN <=100 */
DATA less100_measure  (drop=_NAME_ _LABEL_ rename = (COL1=freq)); 
	SET measure_volume_t (where = (col1<=100));

	if _name_ ^= '_PAGE_'  and _name_^='_TABLE_';
	measure_name = tranwrd(_NAME_, '_N', '');

RUN;
DATA R.less100_measure;SET less100_measure;RUN;*0;

/* CREATE a measure list for count<=100 */
PROC SQL;
	select measure_Name
	into: measure_exclude separated by '' notrim
	from Less100_measure;
QUIT;
%put &measure_exclude;

DATA _null_;
	call symputx('NOBS',NOBS);
	set Less100_measure nobs=NOBS;
RUN;
%put &=NOBS;
*add NOBS variable in Year2025 because of empty 'Less100_measure'. So we can execute dropping &measure_exclude conditionally;

/* REMOVE MEASURES WHICH HAVE HOSPITAL COUNTS <=100*/
DATA initial_data_&year.&quarter;
	SET All_data_&year.&quarter;

	/* drop measure(s) with volume <=100*/
	%if &NOBS>0 %then %do;
  		drop &measure_exclude;
	%end;
RUN;

************************************************************************
* CREATE NEEDED MEASURE NAME LIST                                      *
************************************************************************;
/* CREATE THE FINAL LISTS OF NAME OF INCLUDED MEASURES: &measure_in, &measure_in_std  */
DATA include_measure  (drop=_NAME_ _LABEL_ rename = (COL1=freq)); 
	SET measure_volume_t (where = (col1>100));

	if _name_ ^= '_PAGE_'  and _name_^='_TABLE_';
	measure_in_name = tranwrd(_NAME_, '_N', '');

	measure_in_std = 'std_'||trim(measure_in_name);

RUN;

PROC SQL;
	select measure_in_name into: measure_in separated by '' notrim
	from include_measure;
QUIT;
%put &measure_in;

PROC SQL;
	select measure_in_std into: measure_in_std separated by '' notrim
	from include_measure;
QUIT;

PROC SQL;
	select count(measure_in_name)
	into: measure_cnt
	from include_measure;
QUIT;
%put &measure_cnt;


/* CREATE THE FINAL LISTS OF EACH MEASURE GROUP AND REMOVE THOSE MEASURES WITH <= 100 HOSPITALS */

/* FINAL measuer list for outcome-mortality measure group: &measure_OM  - MUST CHANGE WHEN NEW MEASURE ADDED/REMOVED*/
DATA outcomes_mortality (where = (col1>100)); 
	SET measure_volume_t;

	if _name_ ^= '_PAGE_'  and _name_^='_TABLE_';
	measure_in_name = tranwrd(_NAME_, '_N', '');

	measure_in_std = 'std_'||trim(measure_in_name);

	/*** Here are ALL 7 Mortality measures ***/
	if measure_in_name in /*- MUST CHECK NEXT LINE AND UPDATE FOR EACH QUARTER DATA IF NEW MEASURE ADDED/REMOVED IN THIS QUARTER*/   
	('MORT_30_AMI', 'MORT_30_CABG', 'MORT_30_COPD', 'MORT_30_HF', 'MORT_30_PN', 'MORT_30_STK', 'PSI_4_SURG_COMP');
RUN;

PROC SQL;
	select measure_in_std
	into: measure_OM separated by '' notrim
	from outcomes_mortality;
QUIT;
%put &measure_OM;


/* FINAL measuer list for outcome-safety measure group: &measure_OS  */
DATA outcomes_safety  (where = (col1>100)); 
	SET measure_volume_t;

	if _name_ ^= '_PAGE_'  and _name_^='_TABLE_';
	measure_in_name = tranwrd(_NAME_, '_N', '');

	measure_in_std = 'std_'||trim(measure_in_name);

	/*** Here are ALL 8 SAFETY measures ***/
	if measure_in_name in /*- MUST CHECK NEXT LINE AND UPDATE FOR EACH QUARTER DATA IF NEW MEASURE ADDED/REMOVED IN THIS QUARTER*/ 
	('COMP_HIP_KNEE',  'HAI_1', 'HAI_2', 'HAI_3', 'HAI_4', 'HAI_5', 'HAI_6', 'PSI_90_SAFETY');
RUN;

PROC SQL;
	select measure_in_std  into: measure_OS separated by '' notrim
	from outcomes_safety;
QUIT;
%put &measure_OS;


/* FINAL measuer list for outcome-readmission measure group: &measure_OR  */
DATA outcomes_readmission (where = (col1>100)); 
	SET measure_volume_t;

	if _name_ ^= '_PAGE_'  and _name_^='_TABLE_';
	measure_in_name = tranwrd(_NAME_, '_N', '');

	measure_in_std = 'std_'||trim(measure_in_name);

	/*** Here are ALL 11 READMISSION measures ***/
	if measure_in_name in /*- MUST CHECK NEXT LINE AND UPDATE FOR EACH QUARTER DATA IF NEW MEASURE ADDED/REMOVED IN THIS QUARTER*/ 
	('EDAC_30_AMI', 'EDAC_30_HF', 'EDAC_30_PN', 'OP_32','READM_30_CABG', 'READM_30_COPD', 'READM_30_HIP_KNEE', 
	'READM_30_HOSP_WIDE', 'OP_35_ADM', 'OP_35_ED', 'OP_36');
RUN;

PROC SQL;
	select measure_in_std
	into: measure_OR separated by '' notrim
	from outcomes_readmission;
QUIT;
%put &measure_OR;

/* FINAL measuer list for patient experience measure group: &measure_PtExp */
DATA PtExp (where = (col1>100)); 
	SET measure_volume_t;

	if _name_ ^= '_PAGE_'  and _name_^='_TABLE_';
	measure_in_name = tranwrd(_NAME_, '_N', '');

	measure_in_std = 'std_'||trim(measure_in_name);

	/*** Here are ALL 8 PATIENT EXPERIENCE measures  ***/
	if measure_in_name in /*- MUST CHECK NEXT LINE AND UPDATE FOR EACH QUARTER DATA IF NEW MEASURE ADDED/REMOVED IN THIS QUARTER*/ 
	('H_COMP_1_STAR_RATING', 'H_COMP_2_STAR_RATING', 'H_COMP_3_STAR_RATING', 'H_COMP_5_STAR_RATING', 'H_COMP_6_STAR_RATING',
	'H_COMP_7_STAR_RATING', 'H_GLOB_STAR_RATING', 'H_INDI_STAR_RATING');
RUN;

PROC SQL;
	select measure_in_std
	into: measure_PtExp separated by '' notrim
	from PtExp;
QUIT;
%put &measure_PtExp;



/* FINAL measuer list for Timely and Effective Care group: &measure_Process */

DATA Process (where = (col1>100)); 
	SET measure_volume_t;

	if _name_ ^= '_PAGE_'  and _name_^='_TABLE_';
	measure_in_name = tranwrd(_NAME_, '_N', '');

	measure_in_std = 'std_'||trim(measure_in_name);

	/*** Here are ALL 13Process measures ***/
	if measure_in_name in /*- MUST CHECK NEXT LINE AND UPDATE FOR EACH QUARTER DATA IF NEW MEASURE ADDED/REMOVED IN THIS QUARTER*/ 

	('HCP_COVID_19', 'IMM_3', 'OP_10', 'OP_13', 'OP_18B', /*'OP_2',*/ 'OP_22', 'OP_23', 'OP_29', /*'OP_3B',*/  'OP_8', 'PC_01', 
'SAFE_USE_OF_OPIOIDS', 'SEP_1');
RUN;


PROC SQL;
	select measure_in_std
	into: measure_Process separated by '' notrim
	from Process;
QUIT;
%put &measure_Process;

******************************************************************
* REMOVE HOSPITALS WHICH DO NOT HAVE ANY FINAL INCLUDED MEASURES *
******************************************************************;

%keep_hos(Initial_data_&year.&quarter.,&measure_in,&measure_cnt);


**************************************************************
**Add an output file for mean and standard deviation of measure scores
**************************************************************;
proc means data=Initial_data_&year.&quarter;
	var &measure_in;
	output out=&MEASURE_MEAN;
run;




******************************
* Standardize Measure Scores *
******************************;
PROC STANDARD data=Initial_data_&year.&quarter mean=0 std=1 out=Std_data_&year.&quarter;
	var	&measure_in;
run;

**********************
* RE-DIRECT MEASURES *
**********************;
DATA Std_data_&year.&quarter;
	SET Std_data_&year.&quarter;

	/* flip measures which have negative direction, so all measures are in the same direction 
	   and a higher score means better 
	   -- MUST CHECK AND UPDATE IF MEASURES ARE REMOVED, OR MEASURES ARE ADDED AND NEED TO BE FLIPPED IN NEW QUARTERS*/

	MORT_30_AMI = -MORT_30_AMI;
	MORT_30_CABG = -MORT_30_CABG;
	MORT_30_COPD = -MORT_30_COPD;
	MORT_30_HF = -MORT_30_HF;
	MORT_30_PN = -MORT_30_PN;
	MORT_30_STK = -MORT_30_STK;
	PSI_4_SURG_COMP = -PSI_4_SURG_COMP;

	COMP_HIP_KNEE = -COMP_HIP_KNEE;
	HAI_1= -HAI_1;
	HAI_2= -HAI_2;
	HAI_3= -HAI_3;
	HAI_4= -HAI_4;
	HAI_5= -HAI_5;
	HAI_6= -HAI_6;
	PSI_90_SAFETY = -PSI_90_SAFETY;

	EDAC_30_AMI = -EDAC_30_AMI;
	EDAC_30_HF  = -EDAC_30_HF;
	EDAC_30_PN = -EDAC_30_PN;
	OP_32 = -OP_32;
	READM_30_CABG = -READM_30_CABG;
	READM_30_COPD = -READM_30_COPD;
	READM_30_HIP_KNEE = -READM_30_HIP_KNEE;
	READM_30_HOSP_WIDE = -READM_30_HOSP_WIDE;
	OP_35_ADM= -OP_35_ADM;
	OP_35_ED= -OP_35_ED;
	OP_36= -OP_36;

	OP_22 = -OP_22;
	PC_01 = - PC_01;

	*OP_3B = -OP_3B;*OP_3B is removed in Year 2025;
	OP_18B = -OP_18B;

	OP_8 = -OP_8;
	OP_10 = -OP_10;
	OP_13 = -OP_13;
	SAFE_USE_OF_OPIOIDS=-SAFE_USE_OF_OPIOIDS;*SAFE_USE_OF_OPIOIDS is added in Year 2025;
RUN;



/* OUTPUTS OF 'std_data_2025Jul_analysis' ARE GENERATED*/
DATA &MEASURE_ANALYSIS (drop=i &measure_in);
	SET Std_data_&year.&quarter;

	ARRAY M(&measure_cnt) &measure_in;

    ARRAY Y(&measure_cnt) &measure_in_std; 

    DO I =1 TO &measure_cnt;
       Y[I] = m[I];  
    END;
run;



/*Continue to "1 - First stage_Simple Average of Measure Scores_2025Jul" SAS progam*/

