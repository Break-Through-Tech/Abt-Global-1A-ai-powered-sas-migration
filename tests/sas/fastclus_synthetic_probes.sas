/* Synthetic evidence capture only. No supplied artifacts are read or changed.
   Change probe_dir to an existing writable folder to retain the CSVs after SAS exits.
   This script has not yet been executed against a SAS runtime. */
%let probe_dir=%sysfunc(pathname(work));
%put NOTE: Probe SAS version &sysvlong4;
%put NOTE: Probe output directory &probe_dir;

data percentile_cases;
    length scenario $16;
    input scenario $ score;
    datalines;
five 10
five 20
five 30
five 40
five 50
ties 1
ties 1
ties 1
ties 1
ties 1
ties 2
ties 2
ties 2
ties 2
ties 2
missing 0
missing .
missing 10
missing 20
;
run;
proc sort data=percentile_cases; by scenario; run;
proc univariate data=percentile_cases pctldef=5 noprint;
    by scenario;
    var score;
    output out=percentiles pctlpre=P pctlpts=0 20 40 50 60 80 100;
run;
proc export data=percentiles outfile="&probe_dir/percentiles.csv" dbms=csv replace; run;

/* Separate fixed-seed probe. REPLACE=NONE and MAXITER=0 isolate the STRICT
   boundary; these settings are not substituted into the supplied two-pass macro. */
data boundary_points;
    input id score;
    datalines;
1 0
2 1
3 1.000001
4 .
;
run;
data boundary_seeds;
    input score;
    datalines;
-10
-5
0
5
10
;
run;
proc fastclus data=boundary_points seed=boundary_seeds maxc=5 maxiter=0
    replace=none strict=1 out=strict_boundary;
    var score;
run;
proc export data=strict_boundary outfile="&probe_dir/strict_boundary.csv"
    dbms=csv replace; run;

/* Five separated groups and one outlier expose seed selection and STRICT updates. */
data points;
    input id score;
    datalines;
1 -4.1
2 -4.0
3 -3.9
4 -2.1
5 -2.0
6 -1.9
7 -0.1
8 0.0
9 0.1
10 1.9
11 2.0
12 2.1
13 3.9
14 4.0
15 4.1
16 20.0
;
run;
proc univariate data=points pctldef=5 noprint;
    var score;
    output out=cutoffs pctlpre=P pctlpts=20 40 60 80;
run;
data intervals;
    set points;
    if _n_=1 then set cutoffs;
    if .<score<=P20 then grp=1;
    if P20<score<=P40 then grp=2;
    if P40<score<=P60 then grp=3;
    if P60<score<=P80 then grp=4;
    if P80<score then grp=5;
run;
proc means data=intervals median;
    var score;
    class grp;
    ods output Summary=interval_medians;
run;
data seeds;
    set interval_medians;
    score=score_median;
run;
proc export data=interval_medians outfile="&probe_dir/interval_medians.csv"
    dbms=csv replace; run;

%macro capture(order=normal, reverse=0);
    proc sort data=seeds out=ordered_seeds;
        %if &reverse=1 %then %do; by descending grp; %end;
        %else %do; by grp; %end;
    run;
    proc fastclus data=points maxc=5 converge=0 maxiter=1000 seed=ordered_seeds
        out=pass1 outseed=iterations1 outiter;
        var score;
        ods output ClusterCenters=centers1 ConvergenceStatus=convergence1;
    run;
    proc fastclus data=points maxc=5 converge=0 maxiter=1000 seed=centers1 strict=1
        out=pass2 outseed=iterations2 outiter;
        var score;
        ods output ClusterCenters=centers2 ConvergenceStatus=convergence2;
    run;
    %local i name;
    %do i=1 %to 8;
        %let name=%scan(ordered_seeds iterations1 centers1 convergence1
                        iterations2 centers2 convergence2 pass2, &i);
        proc export data=&name outfile="&probe_dir/&order._&name..csv"
            dbms=csv replace; run;
    %end;
%mend capture;
%capture(order=normal, reverse=0);
%capture(order=reversed, reverse=1);
