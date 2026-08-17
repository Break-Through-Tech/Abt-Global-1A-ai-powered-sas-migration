*Note: it takes less than 5 minutes to run this program;
*****************************************************************;
* SECOND STAGE - 											    *;
* DERIVING SUMMARY SCORE AND STAR RATING                        *;
*														        *;
* SAS 9.4 WIN			   									    *;
*                        									    *;
* YALE CORE 								                    *;
*                        										*;
* For questions, please submit an inquiry to 					*;
* the QualityNet Question & Answer Tool at:						*;
* https://cmsqualitysupport.service-now.com/qnet_qa				*; 
*****************************************************************;

/*This program is used to derive the hospital stars. The summary
  score of each hospital is calculated based on the hospital's
  group(domain) scores which are output from program 1. Then
  the K-means approach is used to derive the hospital star ratings.
*/

/* put all group scores into one file */
data all; 
	merge  R.Outcome_mortality(keep=provider_id grp_score rename =grp_score=Std_Outcomes_Mortality_score)
	       R.Outcome_readmission(keep = provider_id grp_score rename = grp_score=Std_Outcomes_Readmission_score)
	       R.Outcome_safety(keep=provider_id grp_score rename =grp_score=Std_Outcomes_Safety_score)
		   R.Ptexp(keep = provider_id grp_score rename = grp_score=Std_PatientExp_score)
	       R.Process(keep=provider_id grp_score rename = grp_score=Std_Process_score);
	by provider_id;
run;



*********************************************************
*  CALCULATING SUMMARY SCORES BASED ON WEIGHTED AVERAGE *
* 1) fixed standard weights from CMS				    *
* 2) redistribute weights when there is missing group   *
*													    *
*********************************************************;

data summary_score (drop=I1-I5 w1-w5 grp_score1-grp_score5 k sum_weight_ave1-sum_weight_ave5);
	set all;

	array std_weight(5) std_weight_PatientExperience std_weight_Readmission std_weight_Mortality std_weight_safety 
	                   std_weight_Process;

	array w(5) w1-w5;

	array weight(5) weight_PatientExperience weight_Outcomes_Readmission weight_Outcomes_Mortality 
	                weight_Outcomes_Safety weight_Process;

	array score(5)   Std_PatientExp_score Std_Outcomes_Readmission_score Std_Outcomes_Mortality_score 
	                Std_Outcomes_Safety_score Std_Process_score;

	array grp_score(5) grp_score1-grp_score5;
		
	array I(5) I1 I2 I3 I4 I5 ;

	array sum_weight_ave(5) sum_weight_ave1 sum_weight_ave2 sum_weight_ave3 sum_weight_ave4 
	                        sum_weight_ave5;


	/* fixed standard weights from CMS */;
	std_weight_PatientExperience = 0.22;
	std_weight_Readmission = 0.22;
	std_weight_Mortality = 0.22;
	std_weight_safety = 0.22;
	std_weight_Process = 0.12;

	/* create indicator for missing group*/
	do k=1 to 5;
	w[k]= std_weight[k];
	grp_score[k]=score[k];

	if grp_score[k] =. then I[k]=1;
	   else I[k]=0;
	end;

	/* Redistribute weights when there is missing group. For details, please refer to technical report. */
	/*For example, the group of Safety is missing, the weight for Mortality groups is changed 
	from 22/100 to 22/78, the weight for Timely and Effective Care is changed from 12/100 to 12/78.*/
	do k=1 to 5;
	if grp_score[k] =. then weight[k]=.;
	   else weight[k]=W[k]/(1-I1*W1-I2*W2-I3*W3-I4*W4-I5*W5);
	end;

	do k=1 to 5;
	if weight[k] =. then sum_weight_ave[k]=0;
		else sum_weight_ave[k]=weight[k]*score[k];
	end;

	/* summary scores */
	summary_score = sum (of sum_weight_ave1-sum_weight_ave5);
run;


**********************************************************************************************************
** reporting criteria - minimum 3 measures/per group and 3 groups with one of which must be Safety or mortality to receive a Star*
**********************************************************************************************************;
%report(&MEASURE_ANALYSIS, report_indicator, &measure_OM_cnt, &measure_OS_cnt, &measure_OR_cnt, &measure_PtExp_cnt, 
	    &measure_Process_cnt);

/* add reporting indicator and number of measure per measure group to Star output file */
proc sort data=summary_score out=summary_score1;
	by provider_id;
run;

proc sort data=report_indicator;
	by provider_id;
run;

data summary_score21;
	merge summary_score1 report_indicator;
	by provider_id;
run;

/*define peer grouping based on # of groups*/
data summary_score22;
	set summary_score21;
	if report_indicator=1;*for those meeting report criteria;

	total_grp=(Outcomes_Mortality_cnt>=3)  + (Outcomes_safety_cnt>=3)+ (Outcomes_Readmission_cnt>=3)
	+(Patient_Experience_cnt>=3) +(Process_cnt>=3) ;

	if Total_measure_group_cnt=3 then cnt_grp='1) # of groups=3       ';
	if Total_measure_group_cnt=4 then cnt_grp='2) # of groups=4       ';
	if Total_measure_group_cnt=5 then cnt_grp='3) # of groups=5       ';
run;



***********************************
* Generate Star Rating by K-Means for each peer grouping*
***********************************;
data cnt_s10;
	set summary_score22;
	if cnt_grp='1) # of groups=3       '; 
run;
%kmeans(in=cnt_s10, out=cnt_s1,grp=cnt_grp);

data cnt_s20;
	set summary_score22;
	if cnt_grp='2) # of groups=4       ';
run;
%kmeans(in=cnt_s20, out=cnt_s2,grp=cnt_grp);

data cnt_s30;
	set summary_score22;
	if cnt_grp='3) # of groups=5       '; 
run;
%kmeans(in=cnt_s30, out=cnt_s3,grp=cnt_grp);

data cnt_s_str;
	set cnt_s1 cnt_s2 cnt_s3;
run;

proc sort data=cnt_s_str;
	by provider_ID;
run;

data &RESULTS;
	merge Summary_score21 cnt_s_str;
	by provider_ID;
run;


/* OUTPUTS OF 'Star_2025Jul' ARE GENERATED*/
/* label variables, output hospital stars */
data &RESULTS;
	set &RESULTS;

		label provider_id ="Provider ID";
		label summary_score = "Hospital Summary Score";
		label star = "Star Rating";
		label Total_measure_group_cnt = "Number of Measure Groups with >=3 Measuers";
		label MortSafe_group_cnt = "Number of Mortality and Safety Groups with >=3 Measuers";
		label cnt_grp = "Peer Grouping";

		label Outcomes_Mortality_cnt = "Number of Measures in Outcomes-Mortality Group";
		label Outcomes_Safety_cnt = "Number of Measures in Outcomes-Safety Group";
		label Outcomes_Readmission_cnt = "Number of Measures in Outcomes-Readmission Group";
		label Patient_Experience_cnt = "Number of Measures in Patient Experience Group";
        label Process_cnt = "Number of Measures in Timely and Effective Care Group";
				
		label Std_Outcomes_Mortality_score = "Standardized Outcomes-Mortality Group Score";
		label Std_Outcomes_Safety_score = "Standardized Outcomes-Safety Group Score";
		label Std_Outcomes_Readmission_score = "Standardized Outcomes-Readmission Group Score";
		label Std_PatientExp_score = "Standardized Patient Experience Group Score"; 
		label Std_Process_score = "Standardized Timely and Effective Care Group Score"; 

		label report_indicator = "Indicator for reporting Star Rating";
run;

**************************************
** National Average of Group Scores **
**************************************;
%nation_avg0(indata=&RESULTS, out=summary_avg, var=Summary_Score_Nat);
%nation_avg_peer(indata=&RESULTS, out=summary_avg_peer, var=Summary_Score_Nat, gr=Total_measure_group_cnt);

%nation_avg(indata=r.Outcome_mortality, out=outcome_mortality_avg, var=Out_Mrt_Grp_Score_Nat);
%nation_avg(indata=r.Outcome_safety, out=outcome_safety_avg, var=Out_Sft_Grp_Score_Nat);
%nation_avg(indata=r.Outcome_readmission, out=outcome_readmission_avg, var=Out_Readm_grp_Score_Nat);
%nation_avg(indata=r.Ptexp, out=ptexp_avg, var=Pt_Exp_Grp_Score_Nat);
%nation_avg(indata=r.Process, out=process_avg, var=Prc_of_Care_Grp_Score_Nat);


data &NATIONAL_MEAN;
	merge summary_avg summary_avg_peer
		  outcome_mortality_avg outcome_safety_avg outcome_readmission_avg ptexp_avg process_avg 
		  /*outcome_readmission_avg_DE*/;
run;

/* OUTPUTS OF 'national_average_2025Jul' ARE GENERATED*/ 
/* label variables for the national average file, output national average group and summary scores results*/
data &NATIONAL_MEAN;
	set &NATIONAL_MEAN;

		label Summary_Score_Nat = "National Mean of Summary Score";
		label Out_Mrt_Grp_Score_Nat = "National Mean of Outcomes-Mortality Group Score";
		label Out_Sft_Grp_Score_Nat = "National Mean of Outcomes-Safety Group Score";
		label Out_Readm_grp_Score_Nat = "National Mean of Outcomes-Readmission Group Score";
		label Pt_Exp_Grp_Score_Nat = "National Mean of Patient Experience Group Score";
		label Prc_of_Care_Grp_Score_Nat = "National Mean of Timely and Effective Care Group Score";

		label Summary_Score_Nat_Peer3 = "National Mean of Summary Score when # of Groups=3";
		label Summary_Score_Nat_Peer4 = "National Mean of Summary Score when # of Groups=4";
		label Summary_Score_Nat_Peer5 = "National Mean of Summary Score when # of Groups=5";
run;

