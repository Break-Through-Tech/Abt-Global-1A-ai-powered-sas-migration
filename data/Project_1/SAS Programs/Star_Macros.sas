*****************************************************************************
* macro for removing hospitals which do not have any final included measures*
*****************************************************************************;

%macro keep_hos(indsn, varlist, nmeasure);

		data &indsn(where = (Total_m_cnt>=1) drop=c1-c&nmeasure. k); 
			set &indsn;

			array M(&nmeasure.) &varlist.;
			array C (1:&nmeasure.) C1-C&nmeasure.;

	        DO k =1 TO &nmeasure.;
			if m[k] ^=. then C[k]=1;
	   		else C[k]=0;
			END;
			Total_m_cnt=sum(of c1-c&nmeasure.);
		
		run;
%mend;



**********************************************************
* macro for calcuating group score for each measure group*
**********************************************************;

%macro grp_score(indsn, gp, varlist,  nmeasure, Out_avg);
		data dat0 (keep=provider_id &varlist.  c1-c&nmeasure. total_cnt measure_wt avg ); 
			set &indsn.;

			array M(1:&nmeasure.) &varlist.;
			array C (1:&nmeasure.) C1-C&nmeasure.;

	        DO k =1 TO &nmeasure.;
			if m[k] ^=. then C[k]=1;
	   		else C[k]=0;
			END;
			total_cnt=sum(of c1-c&nmeasure.);
			
			if total_cnt>0 then do;
			measure_wt=1/total_cnt;
			avg=sum(of &varlist.)*measure_wt;
			end;
		run;
		
		*standardization of group score;
		PROC STANDARD data=dat0 mean=0 std=1 out=dat1;var avg;run;

		*add mean and stddev into the data;
		ods output summary=new(drop=variable);
		proc means data=dat0 stackodsoutput mean std ;
	 		var avg;
		run;

		proc sql; 
	  		create table dat2 as
	  		select  *
	  		from dat0, new;
		quit;

		data &out_avg;merge dat2(rename=avg=score_before_std) dat1(keep=provider_ID avg rename=avg=grp_score);by provider_ID;run;
%mend;



*********************************
* macro for reporting indicator *
*********************************;

%macro report(indsn, outdsn, nmeasure_OM, nmeasure_OS, nmeasure_OR, nmeasure_PtExp, nmeasure_Process);

	data &outdsn. (keep=provider_id report_indicator Patient_Experience_cnt Outcomes_Readmission_cnt
								Outcomes_Mortality_cnt Outcomes_safety_cnt 
								Process_cnt Total_measure_group_cnt MortSafe_Group_cnt);

		set &indsn.; 

		/* Mortality measures*/
		array Y_M(&nmeasure_OM.) &measure_OM;
		ARRAY M(&nmeasure_OM.) M1-M&nmeasure_OM.;

		DO I =1 TO &nmeasure_OM.;
			if Y_M[I] ^=. then M[I] =1;
			else M[I]=0;
		END;

		Outcomes_Mortality_cnt=sum (of M1-M&nmeasure_OM.);

		/* Saftey measures */
		array Y_S(&nmeasure_OS.) &measure_OS;
		ARRAY S(&nmeasure_OS.) S1-S&nmeasure_OS.;

		DO I =1 TO &nmeasure_OS.;
			if Y_S[I] ^=. then S[I] =1;
			else S[I]=0;
		END;

		Outcomes_safety_cnt=sum (of S1-S&nmeasure_OS.);

		/* Readmisison measures */
		array Y_R(&nmeasure_OR.) &measure_OR;
		ARRAY R(&nmeasure_OR.) R1-R&nmeasure_OR.;

		DO I =1 TO &nmeasure_OR.;
			if Y_R[I] ^=. then R[I] =1;
			else R[I]=0;
		END;

		Outcomes_Readmission_cnt=sum (of R1-R&nmeasure_OR.);

		/* Patient Experience measures */
		array Y_H(&nmeasure_PtExp.)  &measure_PtExp;
		array H(&nmeasure_PtExp.) H1-H&nmeasure_PtExp.;

		DO I =1 TO &nmeasure_PtExp.;
			if Y_H[I] ^=. then H[I] =1;
			else H[I]=0;
		END;

		Patient_Experience_cnt=sum (of H1-H&nmeasure_PtExp.);


		/* Timely and Effective Care measures */
		array Y_PC(&nmeasure_Process.) &measure_Process;
		ARRAY PC(&nmeasure_Process.) PC1-PC&nmeasure_Process.;

		DO I =1 TO &nmeasure_Process.;
			if Y_PC[I] ^=. then PC[I] =1;
			else PC[I]=0;
		END;

		Process_cnt =sum (of PC1-PC&nmeasure_Process.);

		Array D_cnt(5) Patient_Experience_cnt Outcomes_Mortality_cnt Outcomes_Readmission_cnt
		               Outcomes_safety_cnt  Process_cnt;
		Array D(5) D1-D5;

		DO I =1 TO 5;
			if D_cnt[I]>=3 then D[I] =1;
			else D[I]=0;
		END;

		Total_measure_group_cnt =sum (of D1-D5);

		MortSafe_Group_cnt = (Outcomes_Mortality_cnt>=3) + (Outcomes_safety_cnt>=3);

		report_indicator = (MortSafe_Group_cnt>=1) and (Total_measure_group_cnt>=3);

	run;
%mend;


*********************************
* macro for k-means clustering *
*********************************;
%macro kmeans(in=, out=, grp=);
	data summary_score2;
		set &in;
	run;
	*Step1. using quintile medians as intial seeds,  run K-means to complete convergence;
	proc univariate data=summary_score2 noprint;
		var summary_score;
		output out=s1 pctlpre=P pctlpts=20 to 100 by 20;
	run;

	data s2(keep=provider_ID summary_score grp P20 P40 P60 P80);
		set summary_score2;
		if _n_=1 then set s1;

		if .<summary_score<=P20 then grp=1;
		if P20<summary_score<=P40 then grp=2;
		if P40<summary_score<=P60 then grp=3;
		if P60<summary_score<=P80 then grp=4;
		if P80<summary_score then grp=5;
	run;

	proc means data=s2 median;
		var summary_score;class grp;
		ods output summary=s3;
	run;

	data s33;set s3;summary_score=summary_score_median;run;

	/* k-means*/
	proc fastclus data=Summary_score2 maxc=5 converge=0 maxiter=1000 seed=s33;************;
		var	summary_score;

		ods output ClusterCenters=seeds2;
		ods output  ConvergenceStatus=cstatus;
	run;
	proc print data=cstatus;title "QA: FASTCLUS convergence"; run;

	*Step2. using results from Step 1 as initial seeds,  run K-means to complete convergence with 'strict=1' added; 
	*to avoid potential outliers effect on clustering;
	proc fastclus data=Summary_score2 maxc=5 out=clusters converge=0 maxiter=1000 seed=seeds2 strict=1;************;
		var	summary_score;

		ods output ClusterCenters=Cluster_mean;
		ods output  ConvergenceStatus=cstatus2;
	run;
	proc print data=cstatus2;title "QA: FASTCLUS convergence"; run;

	/* order clusters based on mean of summary scores */
	proc sort data=Cluster_mean out=cluster_sort (rename = (summary_score=mean_summary_score_star));
		by summary_score;
	run;

	/* assign Star based on ordered mean of summary scores */
	data cluster_sort (drop=cluster);
		set cluster_sort;
		star=_n_;
		cluster_2=input(cluster,4.);
	run;

	proc sort data=Cluster_sort(rename=(cluster_2=cluster));
		by cluster;
	run;

	data Clusters2;
		set Clusters;
		cluster=abs(cluster);
	run;

	proc sort data=Clusters2;
		by cluster;
	run;

	data RESULTS (drop=cluster distance mean_summary_score_star);
		merge Clusters2  Cluster_sort;
		by cluster;
	run;

	proc sort data=RESULTS;by provider_ID;run;
	data &out;set RESULTS(keep=provider_ID Star &grp );run;

%mend kmeans;


******************************************
** Macro for national average           **
******************************************;
%macro nation_avg0(indata=, out=, var=);
   data temp;
	   set &indata;
	   where report_indicator=1;**********;
	   keep provider_id summary_score;
	run;

	proc sql;
	   create table out1 as
	   select mean(summary_score) as &var from temp;
	quit;
    
	data &out(keep=&var);set out1;run;
%mend;

%macro nation_avg_peer(indata=, out=, var=, gr=);
   data temp;
	   set &indata;
	   where report_indicator=1;**********;
	   keep provider_id summary_score &gr;
	run;

	proc sql;
	   create table out1 as
	   select mean(summary_score) as &var , &gr from temp group by &gr;
	quit;

	proc transpose data=out1 out=out2 prefix=&var._peer;
		var &var;
		id &gr;
	run;

	data &out;
		set out2;
		drop _name_;
	run;
%mend;


%macro nation_avg(indata=, out=, var=);
   data temp;
	   set &indata;
	   where total_cnt>=3;**********;
	   keep provider_id total_cnt grp_score ;
	run;

	proc sql;
	   create table out1 as
	   select mean(grp_score) as &var from temp;
	quit;

	data &out(keep=&var);set out1;run;
%mend;


