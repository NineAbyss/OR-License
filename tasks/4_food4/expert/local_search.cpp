#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <vector>
using namespace std;
int N,L,B; int posmat[6][10], transmat[6][6],pt[6],demand[30][5]; vector<int> st,yp;
double ow,pw;
struct Stats {double score,energy; int cmax,S,v1,v2,r1,r2,r3,changes;};
using Plan=vector<vector<int>>;
bool machine(const vector<int>& s,int m,int &work,int &v1,int &v2,int &r1,int &r2,int &r3,int &changes){
 if((int)s.size()>L)return false;
 int pos=st[m],prev=-1;work=v1=v2=r1=r2=r3=changes=0;bool first_h=false;
 for(int k=0;k<(int)s.size();k++){
  int p=s[k];bool h=false;
  bool pure=pos<10&&posmat[p][pos]&&(prev<0||transmat[prev][p]);
  if(!pure){
   if(pos>=10||!posmat[5][pos]||!posmat[p][0]||!transmat[5][p]||(prev>=0&&!transmat[prev][5]))return false;
   pos=0;prev=-1;h=true;work+=pt[5];changes++;
  }
  if(k==0)first_h=h;
  work+=pt[p];pos++;
  if((prev==1&&(p==1||p==2||p==3))||((prev==2||prev==3)&&p==1))v1++;
  prev=p;
 }
 if(st[m]!=0&&yp[m]!=1&&(s.empty()||(!first_h&&s[0]!=1)))v2=1;
 int a=s.size()>0?s[0]:-1,b=s.size()>1?s[1]:-1;
 r1=(a<0||a>2)+(b<0||b>2);r2=(a<0||a>2||b<0||b>2||a==b);r3=(a!=1&&b!=1);
 return true;
}
bool eval(const Plan& p,Stats& v){
 v={}; int hist[5][30]={};double sq=0,sum=0;int d2=0;
 for(int m=0;m<N;m++){
  int w,z1,z2,z3,z4,z5,h;
  if(!machine(p[m],m,w,z1,z2,z3,z4,z5,h))return false;
  v.cmax=max(v.cmax,w);sum+=w;sq+=w*w;v.v1+=z1;v.v2+=z2;v.r1+=z3;v.r2+=z4;v.r3+=z5;v.changes+=h;
  d2+=(st[m]!=0&&yp[m]!=1);
  for(int k=0;k<(int)p[m].size();k++)hist[p[m][k]][k]++;
 }
 for(int j=0;j<5;j++){
  int b=0,rem=demand[0][j];
  for(int k=0;k<L;k++)for(int q=0;q<hist[j][k];q++){
   while(rem==0&&b+1<B){b++;rem=demand[b][j];}
   if(rem<=0)return false;
   v.S+=k*b;rem--;
  }
  if(rem!=0)return false;
  while(++b<B)if(demand[b][j]!=0)return false;
 }
 double P=max({(double)v.v1/max(1,N*(L-1)),(double)v.v2/max(1,d2),(double)(v.r1+2*v.r2+2*v.r3)/(6*N)});
 v.score=v.cmax-ow*v.S+pw*P;
 v.energy=v.score+0.00003*(sq-sum*sum/N);
 return true;
}
int main(int argc,char**argv){
 if(argc<5)return 2;
 ifstream f(argv[1]);f>>N>>L>>B>>ow>>pw;
 if(N<=0||L<2||L>29||B>30)return 3;
 st.resize(N);yp.resize(N);for(auto& x:st)f>>x;for(auto&x:yp)f>>x;
 for(auto&x:pt)f>>x;
 for(int b=0;b<B;b++)for(int j=0;j<5;j++)f>>demand[b][j];
 for(auto&r:posmat)for(auto&x:r)f>>x;
 for(auto&r:transmat)for(auto&x:r)f>>x;
 Plan original(N);for(auto&r:original){int n;f>>n;r.resize(n);for(auto&x:r)f>>x;}
 int seed=stoi(argv[3]);long long iters=stoll(argv[4]);mt19937 rng(seed);uniform_real_distribution<double>U(0,1);
 Plan current=original,best=original;Stats cs,bs;
 if(!eval(original,cs))return 4;bs=cs;
 auto save=[&](){ofstream o(argv[2]);o<<setprecision(15)<<bs.score<<" "<<bs.cmax<<" "<<bs.S<<" "<<bs.v1<<" "<<bs.v2<<" "<<bs.r1<<" "<<bs.r2<<" "<<bs.r3<<" "<<bs.changes<<"\n";for(auto&r:best){o<<r.size();for(auto x:r)o<<" "<<x;o<<"\n";}};
 save();
 long long cycle=500000;                                                                         
 for(long long it=0;it<iters;it++){
  if(it%cycle==0&&it>0){current=(it/cycle%5==0?original:best);eval(current,cs);}
  double frac=(double)(it%cycle)/cycle;
  double temp=(it/cycle%3==0?3.0:1.2)*pow(0.003,frac);
  int a=rng()%N,b=rng()%N,op=rng()%6;
  auto aa=current[a],bb=current[b];
  if(aa.empty()||bb.empty())continue;
  int i=rng()%aa.size(),j=rng()%bb.size();
  switch(op){
   case 0:case 1:swap(current[a][i],current[b][j]);break;
   case 2:{int p=current[a][i];current[a].erase(current[a].begin()+i);int q=rng()%(current[b].size()+1);current[b].insert(current[b].begin()+q,p);break;}
   case 3:{if(a==b) {if(i>j)swap(i,j);reverse(current[a].begin()+i,current[a].begin()+j+1);}else{current[a].resize(i);current[b].resize(j);current[a].insert(current[a].end(),bb.begin()+j,bb.end());current[b].insert(current[b].end(),aa.begin()+i,aa.end());}break;}
   case 4:{if(a==b) {if(i>j)swap(i,j);rotate(current[a].begin()+i,current[a].begin()+i+1,current[a].begin()+j+1);}else{int la=min((int)(1+rng()%3),(int)aa.size()-i),lb=min((int)(1+rng()%3),(int)bb.size()-j);current[a].erase(current[a].begin()+i,current[a].begin()+i+la);current[a].insert(current[a].begin()+i,bb.begin()+j,bb.begin()+j+lb);current[b].erase(current[b].begin()+j,current[b].begin()+j+lb);current[b].insert(current[b].begin()+j,aa.begin()+i,aa.begin()+i+la);}break;}
   case 5:swap(current[a],current[b]);break;
  }
  Stats ns;
  if(eval(current,ns)&& (ns.energy<cs.energy||U(rng)<exp((cs.energy-ns.energy)/temp))){
   cs=ns;
   if(ns.score<bs.score-1e-9){bs=ns;best=current;save();cerr<<it<<" "<<setprecision(12)<<bs.score<<" C "<<bs.cmax<<" S "<<bs.S<<" V1 "<<bs.v1<<" H "<<bs.changes<<"\n";}
  }else{current[a]=aa;if(a!=b)current[b]=bb;}
 }
 save();return 0;
}
