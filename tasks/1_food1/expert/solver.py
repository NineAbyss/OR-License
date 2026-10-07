

from ortools.linear_solver import pywraplp
import pandas as pd
import numpy as np
import time
import copy
import sys
import json
import os
from pathlib import Path


stateinitial=[6,0,2,3,5,2,6,2,3,0]
demand1=[13,5,6,4,3,2,1,]
demand2=[7,3,2,1,1,1,0]
yuliu=[0,2,4]
yueshu7 =[1 ,1 ,1 ,1 ,1 ,1 ,1 ]

orig_stateinitial = copy.deepcopy(stateinitial)
orig_demand1 = copy.deepcopy(demand1)
orig_demand2 = copy.deepcopy(demand2)
orig_yuliu = copy.deepcopy(yuliu)



lutime =[60, 53, 45, 50, 51, 43, 43, 30 ]

priorityA = ['\u4ea7\u54c1B','\u4ea7\u54c1C','\u4ea7\u54c1D']
priorityB = ['\u4ea7\u54c1E','\u4ea7\u54c1F','\u4ea7\u54c1G']



Weight2=10
Weight25=5
Weightt=0.5
Weighteyy=10
Weight3=1

prodnum=7


guonum=len(stateinitial)
maxquanci=7
M=10000


data_xlsx = Path(
    os.environ.get(
        "FOOD1_DATA_XLSX",
        Path(__file__).resolve().with_name("input_data.xlsx"),
    )
)
df0 = pd.read_excel(data_xlsx,"0",index_col=0).fillna(0)
df1 = pd.read_excel(data_xlsx,"1",index_col=0).fillna(0)
df2 = pd.read_excel(data_xlsx,"2",index_col=0).fillna(0)
df3 = pd.read_excel(data_xlsx,"3",index_col=0).fillna(0)
df4 = pd.read_excel(data_xlsx,"4",index_col=0).fillna(0)
df5 = pd.read_excel(data_xlsx,"5",index_col=0).fillna(0)
df6 = pd.read_excel(data_xlsx,"6",index_col=0).fillna(0)
df7 = pd.read_excel(data_xlsx,"7",index_col=0).fillna(0)
df8 = pd.read_excel(data_xlsx,"8",index_col=0).fillna(0)

g0=df0.replace(('Y','#',7),1)
g1=df1.replace(('Y','#',7,8,'7+8'),1)
g2=df2.replace(('Y','#',7,8,'7+8'),1)
g3=df3.replace(('Y','#',7,8,'7+8','6.5+8'),1)
g4=df4.replace(('Y','#',7,8,'7+8','6.5+8','7.5+8'),1)
g5=df5.replace(('Y','#',7,8,9,'7+8','6.5+8','7.5+8','7+7.5'),1)
g6=df6.replace(('Y','#',7,8,9,'7+8','6.5+8','7.5+8','7+7.5',6.5,77),1)
g7=df7.replace(('Y','#',7,8,9,6.5,7.5,87),1)
g8=df8.replace(('Y','#',8,9,7.5,88,'87+88'),1)


prodname=list(df0.index)

Cguoij0=[g0,g1,g2,g3,g4,g5,g6,g7,g8]
Cguoij1=copy.deepcopy(Cguoij0)
Cguoij1[2].iloc[4:7,6]=1

Cguoij1[3].iloc[4:7,5]=1
Cguoij1[3].iloc[7,6]=1
Cguoij1[4].iloc[4:7,4]=1
Cguoij1[4].iloc[7,5]=1
Cguoij1[5].iloc[4:7,3]=1
Cguoij1[5].iloc[7,4]=1
Cguoij1[6].iloc[4:7,2]=1
Cguoij1[6].iloc[7,3]=1
Cguoij1[7].iloc[4:7,1]=1
Cguoij1[7].iloc[7,2]=1
Cguoij1[7].iloc[0,5]=1
Cguoij1[8].iloc[4:7,0]=1
Cguoij1[8].iloc[7,1]=1
Cguoij1[8].iloc[0,4]=1
Cguoij1[8].iloc[1:4,6]=1
g9 = pd.read_excel(data_xlsx,"9",index_col=0).fillna(0)
Cguoij1.append(g9)



def calculate(level,split,fanganindex,stateinitial,optime,finalt):
    if len(stateinitial)==0:
        print("\u65e0\u89e3\u53c2\u6570\uff1a"+str(split)+str(fanganindex))
        return False,"","","",""

    demand=np.sum([demand1,demand2],axis=0)

    solver = pywraplp.Solver('SolveIntegerProblem',pywraplp.Solver.CBC_MIXED_INTEGER_PROGRAMMING)
    objective = solver.Objective()
    X = [[] for i in range(guonum)]
    Y = [[] for i in range(guonum)]
    eyy=[[] for i in range(guonum)]
    Kai = [[] for i in range(guonum)]


    Z6= [[] for i in range(guonum)]
    Z3= [[] for i in range(guonum)]

    T = [[] for i in range(guonum)]

    T0 = [[] for i in range(guonum)]
    Se0 = [[] for i in range(guonum)]
    Se1 = [[] for i in range(guonum)]
    Se2 = [[] for i in range(guonum)]

    xinlu=[[] for i in range(guonum)]
    conxinlu=[[] for i in range(guonum)]
    conxinlu1=[[] for i in range(guonum)]

    Cons1=[[] for i in range(guonum)]
    Cons0=[[] for i in range(guonum)]
    Consxi=[[] for i in range(guonum)]
    yu=[[] for i in range(guonum)]
    p=[[] for i in range(guonum)]
    Conkai=[[] for i in range(guonum)]
    Tmax = solver.NumVar(0.0, solver.infinity(), "Tmax")
    Tmin = solver.NumVar(0.0, solver.infinity(), "Tmin")
    objective.SetCoefficient(Tmax,Weightt)
    Cons4add=[[] for i in range(guonum)]

    for i in range(guonum):
        eyy[i]=[[] for i in range(maxquanci-1)]

        Z6[i] = solver.IntVar(0.0, 1.0, "Z6"+str(i))
        Z3[i] = solver.IntVar(0.0, 1.0, "Z3"+str(i))
        p[i] = solver.NumVar(0.0, 1.0, "P"+str(i))
        yu[i] = solver.NumVar(0.0, solver.infinity(), "yu"+str(i))
        Kai[i] =  solver.IntVar(0.0, 1.0, "Kai"+str(i))
        Consguoxi=[[] for i in range(2)]
        Consxi[i]=Consguoxi
        Xguo=[[] for i in range(maxquanci)]
        Yguo=[[] for i in range(maxquanci)]
        Cons1guo=[[] for i in range(maxquanci)]
        Cons0guo=[[] for i in range(maxquanci)]
        T[i] = [[] for i in range(maxquanci)]
        T0[i] = [[] for i in range(maxquanci)]
        for j in range(maxquanci-1):
            eyy[i][j]=solver.NumVar(0.0, 1.0, "0ey"+str(i)+"y"+str(j))
        for j in range(maxquanci):
            Xprod=[[] for i in range(prodnum+1)]
            Yprod=[[] for i in range(prodnum+1)]
            Cons1prod=[[] for i in range(prodnum+1)]
            Cons0prod=[[] for i in range(prodnum+1)]
            Xguo[j]=(Xprod)
            Yguo[j]=(Yprod)
            Cons1guo[j]=Cons1prod
            Cons0guo[j]=Cons0prod
        X[i]=(Xguo)
        Y[i]=(Yguo)
        Cons1[i]=Cons1guo
        Cons0[i]=Cons0guo


    for l in range(0, guonum):
        Se0[l] = solver.IntVar(0.0, 1.0, "Se0"+str(l))
        Se1[l] = solver.IntVar(0.0, 1.0, "Se1"+str(l))
        Se2[l] = solver.IntVar(0.0, 1.0, "Se2"+str(l))
        for i in range(0,maxquanci):
            T[l][i] = solver.IntVar(0.0, 1.0, "T"+str(l*10000+i*100))
            T0[l][i] = solver.IntVar(0.0, 1.0, "T0"+str(l*10000+i*100))
            for j in range(0,prodnum+1):

                X[l][i][j] = solver.IntVar(0.0, 1.0, "x"+str(l*10000+i*100+j))
                Y[l][i][j] = solver.IntVar(0.0, 1.0, "Y"+str(l*10000+i*100+j))


                if level <3:
                    Cons1[l][i][j]=solver.Constraint(-solver.infinity(),float(Cguoij0[stateinitial[l]].iloc[j,i]))
                else:
                    Cons1[l][i][j]=solver.Constraint(-solver.infinity(),float(Cguoij1[stateinitial[l]].iloc[j,i]))
                Cons1[l][i][j].SetCoefficient( X[l][i][j],1)
                Cons0[l][i][j]=solver.Constraint(-solver.infinity(),0)
                Cons0[l][i][j].SetCoefficient( Y[l][i][j],1)
                Cons0[l][i][j].SetCoefficient( X[l][i][j],-1)


    for l in range(0,guonum):
        Consxi[l][0]=solver.Constraint(0,0)
        objective.SetCoefficient(yu[l],Weight2)

        for j in range(prodnum):
            Consxi[l][0].SetCoefficient(Y[l][0][j],1)
            Consxi[l][0].SetCoefficient(Y[l][1][j],1)
            Consxi[l][0].SetCoefficient(yu[l],-1)
            Consxi[l][0].SetCoefficient(Kai[l],-2)

    if (split==False):
        Conquan0=solver.Constraint(1,solver.infinity())
        Conquan1=solver.Constraint(1,solver.infinity())
        for l in range(guonum):
            Conquan0.SetCoefficient( X[l][0][0],1)
            Conquan1.SetCoefficient( X[l][0][1],1)
            Conquan1.SetCoefficient( X[l][0][2],1)
            Conquan1.SetCoefficient( X[l][0][3],1)

    Cons2=[[] for i in range(guonum)]
    for i in range(guonum):
        Cons2guo=[[] for i in range(maxquanci)]
        Cons2[i]=Cons2guo
    for l in range(0,guonum):
        for i in range(0,maxquanci-1):
            Cons2[l][i]=solver.Constraint(0,solver.infinity())
            for j in range(0,prodnum):
                Cons2[l][i].SetCoefficient( X[l][i][j],1)
                Cons2[l][i].SetCoefficient( X[l][i+1][j],-1)

    Conkai1=[[] for i in range(guonum)]
    ConT0=[[] for i in range(guonum)]

    Cons60=[[] for i in range(guonum)]
    Cons61=[[] for i in range(guonum)]
    Cons62=[[] for i in range(guonum)]
    Cons63=[[] for i in range(guonum)]
    Consse=[[] for i in range(guonum)]
    for i in range(guonum):
        Cons60guo=[[] for i in range(maxquanci)]
        Cons60[i]=Cons60guo
        Cons61guo=[[] for i in range(maxquanci)]
        Cons61[i]=Cons61guo
        Cons62[i]=Cons61guo
        Cons63[i]=Cons61guo

    Conse1=solver.Constraint(float(yuliu[1]),solver.infinity())
    Conse2=solver.Constraint(float(yuliu[2]),solver.infinity())
    for l in range(guonum):
        Conse1.SetCoefficient(Z3[l],1)
        Conse2.SetCoefficient(Z6[l],1)
        Conkai[l]=solver.Constraint(0,0)
        Conkai[l].SetCoefficient( Kai[l],-1)
        for j in range(prodnum):
            Conkai[l].SetCoefficient(X[l][0][j],1)


        if stateinitial[l]<6 and split==False:
            Conkai1[l]=solver.Constraint(1,solver.infinity())
            Conkai1[l].SetCoefficient( Kai[l],1)


    Cons7=[[] for i in range(guonum)]
    for i in range(guonum):
        Cons7guo=[[] for i in range(maxquanci-3)]
        Cons7[i]=Cons7guo
    for l in range(0,guonum):
        for i in range(0,4):
            Cons7[l][i]=solver.Constraint(-solver.infinity(),1)
            for j in range(0,prodnum):
                Cons7[l][i].SetCoefficient( X[l][i][j],1)

    Cons8=[[] for i in range(guonum)]
    Cons84=[[] for i in range(guonum)]
    Cons87=[[] for i in range(guonum)]
    Cons8p=[[] for i in range(guonum)]
    guonum4=0
    guonum5=0
    for l in range(0,guonum):
        if stateinitial[l]>=4 and stateinitial[l]<=8:
            guonum4+=1
        if stateinitial[l]>=5 and stateinitial[l]<=7:
            guonum5+=1
    if split==False:
        if demand1[4] >=guonum4:
            s1=min(2,guonum4)
            Conschizhong=solver.Constraint(s1,solver.infinity())
            for l in range(0,guonum):
                if stateinitial[l]<=6 and stateinitial[l]>=4:
                    Conschizhong.SetCoefficient( Y[l][(6-stateinitial[l])][4],1)
                elif stateinitial[l]==7 or stateinitial[l]==8:
                    Conschizhong.SetCoefficient( Y[l][0][4],1)

        if demand1[5] >=guonum5:
            s1=min(2,guonum5)
            Conschijian=solver.Constraint(s1,solver.infinity())
            for l in range(0,guonum):
                if stateinitial[l]<=6 and stateinitial[l]>=5:
                    Conschijian.SetCoefficient( Y[l][(7-stateinitial[l])][5],1)
                elif stateinitial[l]==7:
                    Conschijian.SetCoefficient( Y[l][1][5],1)

    for i in range(guonum):
        Cons8guo=[[] for i in range(maxquanci-1)]
        for j in range(maxquanci-1):
            Cons8prod=[[] for i in range(prodnum-1)]
            Cons8guo[j]=Cons8prod
        Cons8[i]=Cons8guo
        Cons84[i]=Cons8guo
        Cons87[i]=[[] for i in range(maxquanci)]
        Cons8p[i]=[[] for i in range(maxquanci-1)]



    if (level==0 or level==3):
        kk=int((sum(demand1)+sum(demand2))/len(stateinitial)-1.2)
    elif(level ==1 or level==4):
        kk=int((sum(demand1)+sum(demand2))/len(stateinitial)-1.5)
    else:
        kk=int((sum(demand1)+sum(demand2))/len(stateinitial)-1.5)-1
    kk=min(5,kk)


    for l in range(0, guonum):
        if kk >= 0:
            Cons8[l][kk][0]=solver.Constraint(1,2)
            for j in range(prodnum):
                Cons8[l][kk][0].SetCoefficient(X[l][kk][j],1)

        for i in range(maxquanci):
            Cons87[l][i]=solver.Constraint(0,solver.infinity())
            Cons87[l][i].SetCoefficient( X[l][i][7],-1)
            Cons87[l][i].SetCoefficient( X[l][i][0],1)

        for i in range(maxquanci-1):

            Cons8p[l][i]=solver.Constraint(0,solver.infinity())
            Cons8p[l][i].SetCoefficient(eyy[l][i],1)
            objective.SetCoefficient(eyy[l][i],Weighteyy)

            for j in range(prodnum):
                Cons8p[l][i].SetCoefficient(Y[l][i][j],1)
                Cons8p[l][i].SetCoefficient(Y[l][i+1][j],-1)

    if(split==False):
        if (level!=2 and level !=5):
            Cons91=solver.Constraint(-solver.infinity(),M)
            Cons92=solver.Constraint(-solver.infinity(),M)

            ss1=solver.IntVar(0.0, 1.0, "SS1"+str(i))
            ss2=solver.IntVar(0.0, 1.0, "SS2"+str(i))

            Cons91.SetCoefficient(ss1,M)
            Cons92.SetCoefficient(ss2,M)

            Con93=solver.Constraint(1,1)
            Con93.SetCoefficient( ss1,1)
            Con93.SetCoefficient( ss2,1)

            for l in range(0, guonum):

                Cons91.SetCoefficient( X[l][0][1],1)
                Cons91.SetCoefficient( X[l][1][1],1)
                Cons92.SetCoefficient( X[l][0][3],1)
                Cons92.SetCoefficient( X[l][1][3],1)

    Cons10=[[] for i in range(prodnum)]


    for j in range(0,prodnum):
        Cons10[j]=solver.Constraint(float(demand[j]),float(demand[j]))
        for l in range(0, guonum):
            for i in range(0,maxquanci):

                Cons10[j].SetCoefficient( X[l][i][j],1)
    if optime==True:
        objective.SetCoefficient(Tmax,Weightt)
        if split==False :
            objective.SetCoefficient(Tmin,-Weightt)

        Con11t=[[] for i in range(guonum)]
        for l in range(guonum):
            Con11t[l]=solver.Constraint(-solver.infinity(),0)
            if split==True:
                Con11t[l]=solver.Constraint(-solver.infinity(),-float(finalt[l]))
            Con11t[l].SetCoefficient(Tmax,-1)


            for i in range(maxquanci):
                for j in range(prodnum+1):
                    Con11t[l].SetCoefficient(X[l][i][j],float(lutime[j]))

        Con11t2=[[] for i in range(guonum)]
        for l in range(guonum):
            Con11t2[l]=solver.Constraint(-solver.infinity(),0)
            if split==True:
                Con11t2[l]=solver.Constraint(-solver.infinity(),float(finalt[l]))
            Con11t2[l].SetCoefficient(Tmin,1)
            for i in range(maxquanci):
                for j in range(prodnum+1):
                    Con11t2[l].SetCoefficient(X[l][i][j],-float(lutime[j]))


    Cons12=[[] for i in range(prodnum)]


    for j in range(0,prodnum):
        Cons12[j]=solver.Constraint(float(demand1[j]),float(demand1[j]))
        for l in range(0, guonum):
            for i in range(0,maxquanci):

                Cons12[j].SetCoefficient( Y[l][i][j],1)

    if yueshu7[0]==1:
        Consextr=[[] for i in range(guonum)]
        ConsextrA1=[[] for i in range(guonum)]
        ConsextrA2=[[] for i in range(guonum)]
        ConsextrB1=[[] for i in range(guonum)]
        ConsextrB2=[[] for i in range(guonum)]
        Consyazhang=[[] for i in range(guonum)]
        Conszhangbo=[[] for i in range(guonum)]

        for l in range(guonum):
            Consextr[l]=[[] for i in range(maxquanci-1)]
            ConsextrA1[l]=[[] for i in range(maxquanci-1)]
            ConsextrA2[l]=[[] for i in range(maxquanci-1)]
            ConsextrB1[l]=[[] for i in range(maxquanci-1)]
            ConsextrB2[l]=[[] for i in range(maxquanci-1)]
            Conszhangbo[l]=[[] for i in range(maxquanci-1)]
            for i in range(maxquanci-1):
                Consextr[l][i]=solver.Constraint(-solver.infinity(),1)
                Consextr[l][i].SetCoefficient(X[l][i][1],1)
                Consextr[l][i].SetCoefficient(X[l][i][2],1)
                Consextr[l][i].SetCoefficient(X[l][i][3],1)
                Consextr[l][i].SetCoefficient(X[l][i+1][0],1)
                Consextr[l][i].SetCoefficient(X[l][i+1][7],-1)
                if level == 0 or level==3:
                    Conszhangbo[l][i]=solver.Constraint(-solver.infinity(),1)
                    Conszhangbo[l][i].SetCoefficient(X[l][i][0],1)
                    Conszhangbo[l][i].SetCoefficient(X[l][i+1][3],1)
                ConsextrB1[l][i]=solver.Constraint(-solver.infinity(),1)
                ConsextrB1[l][i].SetCoefficient(X[l][i][prodname.index(priorityB[1])],1)
                ConsextrB1[l][i].SetCoefficient(X[l][i][prodname.index(priorityB[2])],1)
                ConsextrB1[l][i].SetCoefficient(X[l][i+1][prodname.index(priorityB[0])],1)
                ConsextrB2[l][i]=solver.Constraint(-solver.infinity(),1)
                ConsextrB2[l][i].SetCoefficient(X[l][i][prodname.index(priorityB[2])],1)
                ConsextrB2[l][i].SetCoefficient(X[l][i+1][prodname.index(priorityB[1])],1)
            if split==False:
                if stateinitial[l]<5:
                    if level==0 or level==3:
                        for i in range(4-stateinitial[l]):
                            Consyazhang[l]=solver.Constraint(-solver.infinity(),0)
                            Consyazhang[l].SetCoefficient(X[l][i][3],1)
                    elif level==1 or level==4:
                        if stateinitial[l]<4:
                            for i in range(3-stateinitial[l]):
                                Consyazhang[l]=solver.Constraint(-solver.infinity(),0)
                                Consyazhang[l].SetCoefficient(X[l][i][3],1)


                    for i in range(5-stateinitial[l]):
                        ConsextrA1[l][i]=solver.Constraint(-solver.infinity(),1)
                        ConsextrA1[l][i].SetCoefficient(X[l][i][prodname.index(priorityA[1])],1)
                        ConsextrA1[l][i].SetCoefficient(X[l][i][prodname.index(priorityA[2])],1)
                        ConsextrA1[l][i].SetCoefficient(X[l][i+1][prodname.index(priorityA[0])],1)
                        ConsextrA2[l][i]=solver.Constraint(-solver.infinity(),1)
                        ConsextrA2[l][i].SetCoefficient(X[l][i][prodname.index(priorityA[2])],1)
                        ConsextrA2[l][i].SetCoefficient(X[l][i+1][prodname.index(priorityA[1])],1)
            else:
                    for i in range(maxquanci-1):
                        ConsextrA1[l][i]=solver.Constraint(-solver.infinity(),1)
                        ConsextrA1[l][i].SetCoefficient(X[l][i][prodname.index(priorityA[1])],1)
                        ConsextrA1[l][i].SetCoefficient(X[l][i][prodname.index(priorityA[2])],1)
                        ConsextrA1[l][i].SetCoefficient(X[l][i+1][prodname.index(priorityA[0])],1)
                        ConsextrA2[l][i]=solver.Constraint(-solver.infinity(),1)
                        ConsextrA2[l][i].SetCoefficient(X[l][i][prodname.index(priorityA[2])],1)
                        ConsextrA2[l][i].SetCoefficient(X[l][i+1][prodname.index(priorityA[1])],1)





    Cons14=[[] for i in range(guonum)]


    Cons3=[[] for i in range(guonum)]
    Cons4=[[] for i in range(guonum)]
    Cons5=[[] for i in range(guonum)]
    Consmin=[[] for i in range(guonum)]
    Cons6= [[] for i in range(guonum)]
    S=[[] for i in range(guonum)]
    Conex0=[[] for i in range(guonum)]
    for i in range(len(stateinitial)):
        if stateinitial[i]==0:

            Con40=solver.Constraint(-solver.infinity(),0)
            Con40.SetCoefficient( X[i][6][0],1)
            Con40.SetCoefficient( X[i][6][7],-1)
            Cons4[i]=Con40
            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][6][4],1)
            Con50.SetCoefficient( X[i][6][5],1)
            Con50.SetCoefficient( X[i][6][6],1)
            Con50.SetCoefficient( X[i][6][7],M)
            Cons5[i]=Con50

            Con60=solver.Constraint(0,solver.infinity())
            Con61=solver.Constraint(-solver.infinity(),1)
            Con60.SetCoefficient( Z6[i],-1)
            Con61.SetCoefficient( Z6[i],1)
            for j in range(prodnum+1):
                Con60.SetCoefficient( X[i][5][j],1)
            Con61.SetCoefficient( X[i][6][7],1)
            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][1][0],1)
            Con62.SetCoefficient(Z3[i],-1)
            Con63=solver.Constraint(-solver.infinity(),1)
            Con63.SetCoefficient(X[i][5][1],1)
            Con63.SetCoefficient(X[i][5][2],1)
            Con63.SetCoefficient(X[i][5][3],1)
            Con63.SetCoefficient(Z3[i],1)
            Cons6[i]=[Con60,Con61,Con62,Con63]

            objective.SetCoefficient(X[i][3][2], Weight2)
            objective.SetCoefficient(X[i][6][5], Weight2)
            objective.SetCoefficient(X[i][6][6], Weight2)
            objective.SetCoefficient(X[i][0][0], -Weight25)
            objective.SetCoefficient(X[i][1][0], -Weight25)
            objective.SetCoefficient(X[i][2][0], -Weight25)
            objective.SetCoefficient(X[i][3][1], -Weight25)
            objective.SetCoefficient(X[i][4][2], -Weight25)
            objective.SetCoefficient(X[i][5][3], -Weight25)
            objective.SetCoefficient(X[i][6][4], -Weight25)
            xinlu[i]=solver.IntVar(0.0, 4.0, "xinlu"+str(i))

        elif stateinitial[i]==1:

            Con30=solver.Constraint(-solver.infinity(),1)
            Con30.SetCoefficient( X[i][5][7],1)
            Con30.SetCoefficient( X[i][6][7],1)
            Cons3[i]=Con30
            Con40=solver.Constraint(-solver.infinity(),0)
            Con40.SetCoefficient( X[i][5][0],1)
            Con40.SetCoefficient( X[i][5][7],-1)
            Con41=solver.Constraint(-solver.infinity(),0)
            Con41.SetCoefficient( X[i][6][0],1)
            Con41.SetCoefficient( X[i][5][7],-1)
            Con41.SetCoefficient( X[i][6][7],-1)
            Cons4[i]=[Con40,Con41]
            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][6][4],1)
            Con50.SetCoefficient( X[i][6][5],1)
            Con50.SetCoefficient( X[i][6][6],1)
            Con50.SetCoefficient( X[i][5][4],1)
            Con50.SetCoefficient( X[i][5][5],1)
            Con50.SetCoefficient( X[i][5][6],1)
            Con50.SetCoefficient( X[i][5][7],M)
            Con51=solver.Constraint(-solver.infinity(),M)
            Con51.SetCoefficient( X[i][6][4],1)
            Con51.SetCoefficient( X[i][6][5],1)
            Con51.SetCoefficient( X[i][6][6],1)
            Con51.SetCoefficient( X[i][6][7],M)
            Cons5[i]=[Con50,Con51]

            Con60=solver.Constraint(0,solver.infinity())
            Con60.SetCoefficient( Z6[i],-1)

            Con61=solver.Constraint(-solver.infinity(),M)
            Con61.SetCoefficient( Z6[i],M)
            Con61.SetCoefficient( X[i][5][7],1)
            Con61.SetCoefficient( X[i][6][7],1)

            for j in range(prodnum+1):
                Con60.SetCoefficient( X[i][4][j],1)

            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][0][0],1)
            S1=solver.IntVar(0.0, 1.0, "1S"+str(i))
            S2=solver.IntVar(0.0, 1.0, "2S"+str(i))
            Con62.SetCoefficient(S1,-1)
            Con63=solver.Constraint(-solver.infinity(),1)
            Con63.SetCoefficient(X[i][4][1],1)
            Con63.SetCoefficient(X[i][4][2],1)
            Con63.SetCoefficient(X[i][4][3],1)
            Con63.SetCoefficient(S1,1)
            Con64=solver.Constraint(0,solver.infinity())
            Con64.SetCoefficient(X[i][5][7],1)
            Con64.SetCoefficient(X[i][6][0],1)
            Con64.SetCoefficient(S2,-2)
            Con65=solver.Constraint(0,0)
            Con65.SetCoefficient(S1,1)
            Con65.SetCoefficient(S2,1)
            Con65.SetCoefficient(Z3[i],-1)
            Cons6[i]=[Con60,Con61,Con62,Con63,Con64]

            objective.SetCoefficient(X[i][2][2], Weight2)
            objective.SetCoefficient(X[i][5][5], Weight2)
            objective.SetCoefficient(X[i][5][6], Weight2)
            objective.SetCoefficient(X[i][0][0], -Weight25)
            objective.SetCoefficient(X[i][1][0], -Weight25)
            objective.SetCoefficient(X[i][2][1], -Weight25)
            objective.SetCoefficient(X[i][3][2], -Weight25)
            objective.SetCoefficient(X[i][4][3], -Weight25)
            objective.SetCoefficient(X[i][5][4], -Weight25)
            objective.SetCoefficient(X[i][6][5], -Weight25)
            objective.SetCoefficient(X[i][6][6], -Weight25)


        elif stateinitial[i]==2:
            Con30=solver.Constraint(-solver.infinity(),1)
            Con30.SetCoefficient( X[i][6][7],1)
            Con30.SetCoefficient( X[i][5][7],1)
            Con30.SetCoefficient( X[i][4][7],1)
            Cons3[i]=Con30
            Con40=solver.Constraint(-solver.infinity(),0)
            Con40.SetCoefficient( X[i][4][0],1)
            Con40.SetCoefficient( X[i][6][1],1)
            Con40.SetCoefficient( X[i][6][2],1)
            Con40.SetCoefficient( X[i][6][3],1)
            Con40.SetCoefficient( X[i][4][7],-4)
            Con41=solver.Constraint(-solver.infinity(),0)
            Con41.SetCoefficient( X[i][5][0],1)
            Con41.SetCoefficient( X[i][5][7],-1)
            Con41.SetCoefficient( X[i][4][7],-1)
            Con42=solver.Constraint(-solver.infinity(),0)
            Con42.SetCoefficient( X[i][6][0],1)
            Con42.SetCoefficient( X[i][6][7],-1)
            Con42.SetCoefficient( X[i][5][7],-1)
            Con42.SetCoefficient( X[i][4][7],-1)
            Cons4[i]=[Con40,Con41,Con42]
            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][4][4],1)
            Con50.SetCoefficient( X[i][4][5],1)
            Con50.SetCoefficient( X[i][4][6],1)
            Con50.SetCoefficient( X[i][5][4],1)
            Con50.SetCoefficient( X[i][5][5],1)
            Con50.SetCoefficient( X[i][5][6],1)
            Con50.SetCoefficient( X[i][4][7],M)
            Con51=solver.Constraint(-solver.infinity(),M)
            Con51.SetCoefficient( X[i][5][4],1)
            Con51.SetCoefficient( X[i][5][5],1)
            Con51.SetCoefficient( X[i][5][6],1)
            Con51.SetCoefficient( X[i][5][7],M)
            Cons5[i]=[Con50,Con51]
            if level >=3:
                Con50.SetCoefficient( X[i][6][4],1)
                Con50.SetCoefficient( X[i][6][5],1)
                Con50.SetCoefficient( X[i][6][6],1)
                Con51.SetCoefficient( X[i][6][4],1)
                Con51.SetCoefficient( X[i][6][5],1)
                Con51.SetCoefficient( X[i][6][6],1)
                Con52=solver.Constraint(-solver.infinity(),M)
                Con52.SetCoefficient( X[i][6][4],1)
                Con52.SetCoefficient( X[i][6][5],1)
                Con52.SetCoefficient( X[i][6][6],1)
                Con52.SetCoefficient( X[i][6][7],M)
                Cons5[i]=[Con50,Con51,Con52]

            Con60=solver.Constraint(0,solver.infinity())
            Con60.SetCoefficient( Z6[i],-1)
            Con61=solver.Constraint(-solver.infinity(),M)
            Con61.SetCoefficient( Z6[i],M)
            Con61.SetCoefficient( X[i][4][7],1)
            Con61.SetCoefficient( X[i][5][7],1)
            for j in range(prodnum+1):
                Con60.SetCoefficient( X[i][3][j],1)
                Con61.SetCoefficient( X[i][6][j],1)
            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][5][7],1)
            Con62.SetCoefficient(X[i][6][0],1)
            S1=solver.IntVar(0.0, 1.0, "1S"+str(i))
            S2=solver.IntVar(0.0, 1.0, "2S"+str(i))
            S3=solver.IntVar(0.0, 1.0, "3S"+str(i))
            Con62.SetCoefficient(S3,-2)
            Con63=solver.Constraint(-solver.infinity(),1)
            Con63.SetCoefficient(X[i][3][1],1)
            Con63.SetCoefficient(X[i][3][2],1)
            Con63.SetCoefficient(X[i][3][3],1)
            Con63.SetCoefficient(S1,1)
            Con64=solver.Constraint(0,solver.infinity())
            Con64.SetCoefficient(X[i][4][7],1)
            Con64.SetCoefficient(X[i][5][0],1)
            Con64.SetCoefficient(S2,-2)
            Con65=solver.Constraint(0,0)
            Con65.SetCoefficient(S1,1)
            Con65.SetCoefficient(S2,1)
            Con65.SetCoefficient(S3,1)
            Con65.SetCoefficient(Z3[i],-1)
            Cons6[i]=[Con60,Con61,Con62,Con63,Con64]

            objective.SetCoefficient(X[i][1][2], Weight2)
            objective.SetCoefficient(X[i][4][5], Weight2)
            objective.SetCoefficient(X[i][4][6], Weight2)
            objective.SetCoefficient(X[i][5][4], Weight2)
            objective.SetCoefficient(X[i][6][4], Weight2)
            objective.SetCoefficient(X[i][0][0], -Weight25)
            objective.SetCoefficient(X[i][1][1], -Weight25)
            objective.SetCoefficient(X[i][2][2], -Weight25)
            objective.SetCoefficient(X[i][3][3], -Weight25)
            objective.SetCoefficient(X[i][4][4], -Weight25)
            objective.SetCoefficient(X[i][5][5], -Weight25)
            objective.SetCoefficient(X[i][5][6], -Weight25)
            objective.SetCoefficient(X[i][6][0], -Weight25)
            xinlu[i]=solver.IntVar(-4.0, 4.0, "xinlu"+str(i))
            conxinlu[i]=solver.Constraint(-solver.infinity(),3)
            conxinlu[i].SetCoefficient(X[i][4][0],1)
            conxinlu[i].SetCoefficient(X[i][5][0],1)
            conxinlu[i].SetCoefficient(X[i][6][0],1)
            conxinlu[i].SetCoefficient(xinlu[i],-1)
            conxinlu1[i]=solver.Constraint(3,solver.infinity())
            conxinlu1[i].SetCoefficient(X[i][4][0],1)
            conxinlu1[i].SetCoefficient(X[i][5][0],1)
            conxinlu1[i].SetCoefficient(X[i][6][0],1)
            conxinlu1[i].SetCoefficient(xinlu[i],-1)

        elif stateinitial[i]==3:
            Con30=solver.Constraint(-solver.infinity(),1)
            Con30.SetCoefficient( X[i][3][7],1)
            Con30.SetCoefficient( X[i][4][7],1)
            Con30.SetCoefficient( X[i][5][7],1)
            if level>=3:
                Con30.SetCoefficient( X[i][6][7],1)
            Cons3[i]=Con30
            Con40=solver.Constraint(-solver.infinity(),0)
            Con40.SetCoefficient( X[i][3][0],1)
            Con40.SetCoefficient( X[i][5][1],1)
            Con40.SetCoefficient( X[i][5][2],1)
            Con40.SetCoefficient( X[i][5][3],1)
            Con40.SetCoefficient( X[i][3][7],-4)
            Con41=solver.Constraint(-solver.infinity(),0)
            Con41.SetCoefficient( X[i][4][0],1)
            Con41.SetCoefficient( X[i][6][1],1)
            Con41.SetCoefficient( X[i][6][2],1)
            Con41.SetCoefficient( X[i][6][3],1)
            Con41.SetCoefficient( X[i][3][7],-4)
            Con41.SetCoefficient( X[i][4][7],-4)
            if (level <3):
                Con42=solver.Constraint(-solver.infinity(),0)
                Con42.SetCoefficient( X[i][6][0],1)
                Con42.SetCoefficient( X[i][5][0],1)
                Con42.SetCoefficient( X[i][3][7],-2)
                Con42.SetCoefficient( X[i][4][7],-2)
                Con42.SetCoefficient( X[i][5][7],-2)
                Cons4[i]=[Con40,Con41,Con42]
            elif(level>=3):
                Con42=solver.Constraint(-solver.infinity(),0)
                Con42.SetCoefficient( X[i][5][0],1)
                Con42.SetCoefficient( X[i][3][7],-1)
                Con42.SetCoefficient( X[i][4][7],-1)
                Con42.SetCoefficient( X[i][5][7],-1)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][6][0],1)
                Con43.SetCoefficient( X[i][3][7],-1)
                Con43.SetCoefficient( X[i][4][7],-1)
                Con43.SetCoefficient( X[i][5][7],-1)
                Con43.SetCoefficient( X[i][6][7],-1)
                Cons4[i]=[Con40,Con41,Con42,Con43]


            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][4][4],1)
            Con50.SetCoefficient( X[i][4][5],1)
            Con50.SetCoefficient( X[i][4][6],1)
            Con50.SetCoefficient( X[i][3][4],1)
            Con50.SetCoefficient( X[i][3][5],1)
            Con50.SetCoefficient( X[i][3][6],1)
            Con50.SetCoefficient( X[i][3][7],M)
            Con51=solver.Constraint(-solver.infinity(),M)
            Con51.SetCoefficient( X[i][4][4],1)
            Con51.SetCoefficient( X[i][4][5],1)
            Con51.SetCoefficient( X[i][4][6],1)
            Con51.SetCoefficient( X[i][4][7],M)
            Cons5[i]=[Con50,Con51]
            if level >=3:
                Con50.SetCoefficient( X[i][5][4],1)
                Con50.SetCoefficient( X[i][5][5],1)
                Con50.SetCoefficient( X[i][5][6],1)
                Con51.SetCoefficient( X[i][5][4],1)
                Con51.SetCoefficient( X[i][5][5],1)
                Con51.SetCoefficient( X[i][5][6],1)
                Con52=solver.Constraint(-solver.infinity(),M)
                Con52.SetCoefficient( X[i][5][4],1)
                Con52.SetCoefficient( X[i][5][5],1)
                Con52.SetCoefficient( X[i][5][6],1)
                Con52.SetCoefficient( X[i][5][7],M)
                Cons5[i]=[Con50,Con51,Con52]

            Con60=solver.Constraint(0,solver.infinity())
            Con60.SetCoefficient( Z6[i],-1)
            Con61=solver.Constraint(-solver.infinity(),M)
            Con61.SetCoefficient( Z6[i],M)
            Con61.SetCoefficient( X[i][3][7],1)
            Con61.SetCoefficient( X[i][4][7],1)
            for j in range(prodnum+1):
                Con60.SetCoefficient( X[i][2][j],1)
                Con61.SetCoefficient( X[i][5][j],1)
            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][5][7],1)
            Con62.SetCoefficient(X[i][6][0],1)
            S1=solver.IntVar(0.0, 1.0, "1S"+str(i))
            S2=solver.IntVar(0.0, 1.0, "2S"+str(i))
            S3=solver.IntVar(0.0, 1.0, "3S"+str(i))
            S4=solver.IntVar(0.0, 1.0, "4S"+str(i))
            Con62.SetCoefficient(S3,-2)
            Con63=solver.Constraint(0,solver.infinity())
            Con63.SetCoefficient(X[i][3][7],1)
            Con63.SetCoefficient(X[i][4][0],1)
            Con63.SetCoefficient(S1,-2)
            Con64=solver.Constraint(0,solver.infinity())
            Con64.SetCoefficient(X[i][4][7],1)
            Con64.SetCoefficient(X[i][5][0],1)
            Con64.SetCoefficient(S2,-2)
            Con65=solver.Constraint(-solver.infinity(),1)
            Con65.SetCoefficient(S4,1)
            Con65.SetCoefficient(X[i][2][1],1)
            Con65.SetCoefficient(X[i][2][2],1)
            Con65.SetCoefficient(X[i][2][3],1)
            Con66=solver.Constraint(0,0)
            Con66.SetCoefficient(S1,1)
            Con66.SetCoefficient(S2,1)
            Con66.SetCoefficient(S3,1)
            Con66.SetCoefficient(S4,1)
            Con66.SetCoefficient(Z3[i],-1)

            Cons6[i]=[Con60,Con61,Con62,Con63,Con64]

            objective.SetCoefficient(X[i][0][2], Weight2)
            objective.SetCoefficient(X[i][3][5], Weight2)
            objective.SetCoefficient(X[i][3][6], Weight2)
            objective.SetCoefficient(X[i][5][4], Weight2)
            objective.SetCoefficient(X[i][4][4], Weight2)
            objective.SetCoefficient(X[i][0][1], -Weight25)
            objective.SetCoefficient(X[i][1][2], -Weight25)
            objective.SetCoefficient(X[i][2][3], -Weight25)
            objective.SetCoefficient(X[i][3][4], -Weight25)
            objective.SetCoefficient(X[i][4][5], -Weight25)
            objective.SetCoefficient(X[i][4][6], -Weight25)
            objective.SetCoefficient(X[i][5][0], -Weight25)
            objective.SetCoefficient(X[i][6][0], -Weight25)
            p1=solver.IntVar(0.0, 1.0, "p1"+str(i))
            objective.SetCoefficient(p1, Weight2)
            Con71=solver.Constraint(-solver.infinity(),M)
            Con71.SetCoefficient(X[i][6][2],1)
            Con71.SetCoefficient(p1,-1)
            Con71.SetCoefficient(X[i][3][7],M)
            Con72=solver.Constraint(0,solver.infinity())
            Con72.SetCoefficient(p1,1)
            Con72.SetCoefficient(X[i][3][7],M)
            Consmin[i]=[Con71,Con72]
            xinlu[i]=solver.IntVar(-4.0, 4.0, "xinlu"+str(i))
            conxinlu[i]=solver.Constraint(3,3)
            conxinlu[i].SetCoefficient(X[i][3][0],1)
            conxinlu[i].SetCoefficient(X[i][4][0],1)
            conxinlu[i].SetCoefficient(X[i][5][0],1)
            conxinlu[i].SetCoefficient(X[i][6][0],1)
            conxinlu[i].SetCoefficient(xinlu[i],-1)
        elif stateinitial[i]==4:
            Con30=solver.Constraint(-solver.infinity(),1)
            Con30.SetCoefficient( X[i][4][7],1)
            Con30.SetCoefficient( X[i][3][7],1)
            Con30.SetCoefficient( X[i][2][7],1)
            if (level>=3):
                Con30.SetCoefficient( X[i][5][7],1)
            Cons3[i]=Con30
            Con40=solver.Constraint(-solver.infinity(),0)
            Con40.SetCoefficient( X[i][2][0],1)
            Con40.SetCoefficient( X[i][4][1],1)
            Con40.SetCoefficient( X[i][4][2],1)
            Con40.SetCoefficient( X[i][4][3],1)
            Con40.SetCoefficient( X[i][2][7],-4)
            Con41=solver.Constraint(-solver.infinity(),0)
            Con41.SetCoefficient( X[i][3][0],1)
            Con41.SetCoefficient( X[i][5][1],1)
            Con41.SetCoefficient( X[i][5][2],1)
            Con41.SetCoefficient( X[i][5][3],1)
            Con41.SetCoefficient( X[i][3][7],-M)
            Con41.SetCoefficient( X[i][2][7],-M)
            if (level <3):
                Con42=solver.Constraint(-solver.infinity(),0)
                Con42.SetCoefficient( X[i][6][0],1)
                Con42.SetCoefficient( X[i][4][7],-1)
                Con42.SetCoefficient( X[i][3][7],-1)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][6][1],1)
                Con43.SetCoefficient( X[i][6][2],1)
                Con43.SetCoefficient( X[i][6][3],1)
                Con43.SetCoefficient( X[i][4][0],1)
                Con43.SetCoefficient( X[i][5][0],1)
                Con43.SetCoefficient( X[i][4][7],-M)
                Con43.SetCoefficient( X[i][3][7],-M)
                Con43.SetCoefficient( X[i][2][7],-M)
                Cons4[i]=[Con40,Con41,Con42,Con43]
            elif(level>=3):
                Con42=solver.Constraint(-solver.infinity(),0)
                Con42.SetCoefficient( X[i][6][0],1)
                Con42.SetCoefficient( X[i][4][7],-1)
                Con42.SetCoefficient( X[i][3][7],-1)
                Con42.SetCoefficient( X[i][5][7],-1)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][6][1],1)
                Con43.SetCoefficient( X[i][6][2],1)
                Con43.SetCoefficient( X[i][6][3],1)
                Con43.SetCoefficient( X[i][4][0],1)
                Con43.SetCoefficient( X[i][4][7],-M)
                Con43.SetCoefficient( X[i][3][7],-M)
                Con43.SetCoefficient( X[i][2][7],-M)
                Con44=solver.Constraint(-solver.infinity(),0)
                Con44.SetCoefficient( X[i][5][0],1)
                Con44.SetCoefficient( X[i][5][7],-M)
                Con44.SetCoefficient( X[i][4][7],-M)
                Con44.SetCoefficient( X[i][3][7],-M)
                Con44.SetCoefficient( X[i][2][7],-M)
                Cons4[i]=[Con40,Con41,Con42,Con43,Con44]

            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][3][4],1)
            Con50.SetCoefficient( X[i][3][5],1)
            Con50.SetCoefficient( X[i][3][6],1)
            Con50.SetCoefficient( X[i][2][4],1)
            Con50.SetCoefficient( X[i][2][5],1)
            Con50.SetCoefficient( X[i][2][6],1)
            Con50.SetCoefficient( X[i][2][7],M)
            Con51=solver.Constraint(-solver.infinity(),M)
            Con51.SetCoefficient( X[i][3][4],1)
            Con51.SetCoefficient( X[i][3][5],1)
            Con51.SetCoefficient( X[i][3][6],1)
            Con51.SetCoefficient( X[i][3][7],M)
            Cons5[i]=[Con50,Con51]
            if level >=3:
                Con50.SetCoefficient( X[i][4][4],1)
                Con50.SetCoefficient( X[i][4][5],1)
                Con50.SetCoefficient( X[i][4][6],1)
                Con51.SetCoefficient( X[i][4][4],1)
                Con51.SetCoefficient( X[i][4][5],1)
                Con51.SetCoefficient( X[i][4][6],1)
                Con52=solver.Constraint(-solver.infinity(),M)
                Con52.SetCoefficient( X[i][4][4],1)
                Con52.SetCoefficient( X[i][4][5],1)
                Con52.SetCoefficient( X[i][4][6],1)
                Con52.SetCoefficient( X[i][4][7],M)
                Cons5[i]=[Con50,Con51,Con52]

            Con60=solver.Constraint(0,solver.infinity())
            Con60.SetCoefficient( Z6[i],-1)
            Con61=solver.Constraint(-solver.infinity(),M)
            Con61.SetCoefficient( Z6[i],M)
            Con61.SetCoefficient( X[i][2][7],1)
            Con61.SetCoefficient( X[i][3][7],1)
            for j in range(prodnum+1):
                Con60.SetCoefficient( X[i][1][j],1)
                Con61.SetCoefficient( X[i][4][j],1)
            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][5][7],1)
            Con62.SetCoefficient(X[i][6][0],1)
            S1=solver.IntVar(0.0, 1.0, "1S"+str(i))
            S2=solver.IntVar(0.0, 1.0, "2S"+str(i))
            S3=solver.IntVar(0.0, 1.0, "3S"+str(i))
            S4=solver.IntVar(0.0, 1.0, "4S"+str(i))
            S5=solver.IntVar(0.0, 1.0, "5S"+str(i))
            Con62.SetCoefficient(S3,-2)
            Con63=solver.Constraint(0,solver.infinity())
            Con63.SetCoefficient(X[i][3][7],1)
            Con63.SetCoefficient(X[i][4][0],1)
            Con63.SetCoefficient(S1,-2)
            Con64=solver.Constraint(0,solver.infinity())
            Con64.SetCoefficient(X[i][4][7],1)
            Con64.SetCoefficient(X[i][5][0],1)
            Con64.SetCoefficient(S2,-2)
            Con644=solver.Constraint(0,solver.infinity())
            Con644.SetCoefficient(X[i][2][7],1)
            Con644.SetCoefficient(X[i][3][0],1)
            Con644.SetCoefficient(S5,-2)
            Con65=solver.Constraint(-solver.infinity(),1)
            Con65.SetCoefficient(S4,1)
            Con65.SetCoefficient(X[i][1][1],1)
            Con65.SetCoefficient(X[i][1][2],1)
            Con65.SetCoefficient(X[i][1][3],1)
            Con66=solver.Constraint(0,0)
            Con66.SetCoefficient(S1,1)
            Con66.SetCoefficient(S2,1)
            Con66.SetCoefficient(S3,1)
            Con66.SetCoefficient(S4,1)
            Con66.SetCoefficient(S5,1)
            Con66.SetCoefficient(Z3[i],-1)

            Cons6[i]=[Con60,Con61,Con62,Con63,Con64]

            objective.SetCoefficient(X[i][2][5], Weight2)
            objective.SetCoefficient(X[i][2][6], Weight2)
            objective.SetCoefficient(X[i][3][4], Weight2)
            objective.SetCoefficient(X[i][4][4], Weight2)
            objective.SetCoefficient(X[i][0][2], -Weight25)
            objective.SetCoefficient(X[i][1][3], -Weight25)
            objective.SetCoefficient(X[i][2][4], -Weight25)
            objective.SetCoefficient(X[i][3][5], -Weight25)
            objective.SetCoefficient(X[i][3][6], -Weight25)
            objective.SetCoefficient(X[i][4][0], -Weight25)
            objective.SetCoefficient(X[i][5][0], -Weight25)
            objective.SetCoefficient(X[i][6][0], -Weight25)
            p1=solver.IntVar(0.0, 1.0, "p1"+str(i))
            p2=solver.IntVar(0.0, 1.0, "p2"+str(i))
            objective.SetCoefficient(p1, Weight2)
            objective.SetCoefficient(p2, Weight2)
            Con71=solver.Constraint(-solver.infinity(),M)
            Con71.SetCoefficient(X[i][5][2],1)
            Con71.SetCoefficient(p1,-1)
            Con71.SetCoefficient(X[i][2][7],M)
            Con72=solver.Constraint(0,solver.infinity())
            Con72.SetCoefficient(p1,1)
            Con72.SetCoefficient(X[i][2][7],M)
            Con73=solver.Constraint(-solver.infinity(),M)
            Con73.SetCoefficient(X[i][6][2],1)
            Con73.SetCoefficient(p2,-1)
            Con73.SetCoefficient(X[i][3][7],M)
            Con74=solver.Constraint(0,solver.infinity())
            Con74.SetCoefficient(p2,1)
            Con74.SetCoefficient(X[i][3][7],M)
            Consmin[i]=[Con71,Con72,Con73,Con74]
            xinlu[i]=solver.IntVar(-4.0, 4.0, "xinlu"+str(i))
            conxinlu[i]=solver.Constraint(3,3)
            conxinlu[i].SetCoefficient(X[i][2][0],1)
            conxinlu[i].SetCoefficient(X[i][3][0],1)
            conxinlu[i].SetCoefficient(X[i][4][0],1)
            conxinlu[i].SetCoefficient(X[i][5][0],1)
            conxinlu[i].SetCoefficient(X[i][6][0],1)
            conxinlu[i].SetCoefficient(xinlu[i],-1)
        elif stateinitial[i]==5:
            objective.SetCoefficient(Y[i][3][4], 10*Weight2)
            objective.SetCoefficient(Y[i][3][5], 10*Weight2)
            objective.SetCoefficient(Y[i][4][4], 20*Weight2)
            objective.SetCoefficient(Y[i][4][5], 20*Weight2)
            objective.SetCoefficient(Y[i][5][4], 30*Weight2)
            objective.SetCoefficient(Y[i][5][5], 30*Weight2)
            objective.SetCoefficient(Y[i][6][4], 40*Weight2)
            objective.SetCoefficient(Y[i][6][5], 40*Weight2)
            Con30=solver.Constraint(-solver.infinity(),1)
            Con30.SetCoefficient( X[i][1][7],1)
            Con30.SetCoefficient( X[i][2][7],1)
            Con30.SetCoefficient( X[i][3][7],1)
            if (level>=3):
                Con30.SetCoefficient( X[i][4][7],1)
            Cons3[i]=Con30
            Con40=solver.Constraint(-solver.infinity(),0)
            Con40.SetCoefficient( X[i][1][0],1)
            Con40.SetCoefficient( X[i][3][1],1)
            Con40.SetCoefficient( X[i][3][2],1)
            Con40.SetCoefficient( X[i][3][3],1)
            Con40.SetCoefficient( X[i][1][7],-4)
            Con41=solver.Constraint(-solver.infinity(),0)
            Con41.SetCoefficient( X[i][2][0],1)
            Con41.SetCoefficient( X[i][4][0],1)
            Con41.SetCoefficient( X[i][4][1],1)
            Con41.SetCoefficient( X[i][4][2],1)
            Con41.SetCoefficient( X[i][4][3],1)
            Con41.SetCoefficient( X[i][1][7],-M)
            Con41.SetCoefficient( X[i][2][7],-M)
            Con42=solver.Constraint(-solver.infinity(),0)
            if (level<3):
                Con42.SetCoefficient( X[i][3][0],1)
                Con42.SetCoefficient( X[i][4][0],1)
                Con42.SetCoefficient( X[i][5][1],1)
                Con42.SetCoefficient( X[i][5][2],1)
                Con42.SetCoefficient( X[i][5][3],1)
                Con42.SetCoefficient( X[i][6][1],1)
                Con42.SetCoefficient( X[i][6][2],1)
                Con42.SetCoefficient( X[i][6][3],1)
                Con42.SetCoefficient( X[i][2][7],-M)
                Con42.SetCoefficient( X[i][1][7],-M)
                Con42.SetCoefficient( X[i][3][7],-M)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][5][0],1)
                Con43.SetCoefficient( X[i][2][7],-M)
                Con43.SetCoefficient( X[i][3][7],-M)
                Con44=solver.Constraint(-solver.infinity(),0)
                Con44.SetCoefficient( X[i][6][0],1)
                Con44.SetCoefficient( X[i][3][7],-1)
                Cons4[i]=[Con40,Con41,Con42,Con43,Con44]
            elif(level>=3):
                Con42.SetCoefficient( X[i][3][0],1)
                Con42.SetCoefficient( X[i][5][1],1)
                Con42.SetCoefficient( X[i][5][2],1)
                Con42.SetCoefficient( X[i][5][3],1)
                Con42.SetCoefficient( X[i][2][7],-M)
                Con42.SetCoefficient( X[i][1][7],-M)
                Con42.SetCoefficient( X[i][3][7],-M)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][4][0],1)
                Con43.SetCoefficient( X[i][6][1],1)
                Con43.SetCoefficient( X[i][6][2],1)
                Con43.SetCoefficient( X[i][6][3],1)
                Con43.SetCoefficient( X[i][2][7],-M)
                Con43.SetCoefficient( X[i][3][7],-M)
                Con43.SetCoefficient( X[i][1][7],-M)
                Con43.SetCoefficient( X[i][4][7],-M)
                Con44=solver.Constraint(-solver.infinity(),0)
                Con44.SetCoefficient( X[i][6][0],1)
                Con44.SetCoefficient( X[i][3][7],-1)
                Con44.SetCoefficient( X[i][4][7],-1)
                Con45=solver.Constraint(-solver.infinity(),0)
                Con45.SetCoefficient( X[i][5][0],1)
                Con45.SetCoefficient( X[i][2][7],-1)
                Con45.SetCoefficient( X[i][3][7],-1)
                Con45.SetCoefficient( X[i][4][7],-1)
                Cons4[i]=[Con40,Con41,Con42,Con43,Con44,Con45]
            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][1][4],1)
            Con50.SetCoefficient( X[i][1][5],1)
            Con50.SetCoefficient( X[i][1][6],1)
            Con50.SetCoefficient( X[i][2][4],1)
            Con50.SetCoefficient( X[i][2][5],1)
            Con50.SetCoefficient( X[i][2][6],1)
            Con50.SetCoefficient( X[i][1][7],M)
            Con51=solver.Constraint(-solver.infinity(),M)
            Con51.SetCoefficient( X[i][2][4],1)
            Con51.SetCoefficient( X[i][2][5],1)
            Con51.SetCoefficient( X[i][2][6],1)
            Con51.SetCoefficient( X[i][2][7],M)
            Cons5[i]=[Con50,Con51]
            if level >=3:
                Con50.SetCoefficient( X[i][3][4],1)
                Con50.SetCoefficient( X[i][3][5],1)
                Con50.SetCoefficient( X[i][3][6],1)
                Con51.SetCoefficient( X[i][3][4],1)
                Con51.SetCoefficient( X[i][3][5],1)
                Con51.SetCoefficient( X[i][3][6],1)
                Con52=solver.Constraint(-solver.infinity(),M)
                Con52.SetCoefficient( X[i][3][4],1)
                Con52.SetCoefficient( X[i][3][5],1)
                Con52.SetCoefficient( X[i][3][6],1)
                Con52.SetCoefficient( X[i][3][7],M)
                Cons5[i]=[Con50,Con51,Con52]

            S11=solver.IntVar(0.0, 1.0, "11S"+str(i))
            S12=solver.IntVar(0.0, 1.0, "21S"+str(i))
            Con60=solver.Constraint(0,solver.infinity())
            Con60.SetCoefficient( S11,-1)
            Con61=solver.Constraint(-solver.infinity(),M)
            Con61.SetCoefficient( S11,M)
            Con61.SetCoefficient( X[i][1][7],1)
            Con61.SetCoefficient( X[i][2][7],1)
            for j in range(prodnum+1):
                Con60.SetCoefficient( X[i][0][j],1)
                Con61.SetCoefficient( X[i][3][j],1)
            Con601=solver.Constraint(0,solver.infinity())
            Con601.SetCoefficient( X[i][1][7],1)
            Con601.SetCoefficient( X[i][6][1],1)
            Con601.SetCoefficient( X[i][6][2],1)
            Con601.SetCoefficient( X[i][6][3],1)
            Con601.SetCoefficient( S12,-2)
            Con602=solver.Constraint(0,0)
            Con602.SetCoefficient( S11,1)
            Con602.SetCoefficient( S12,1)
            Con602.SetCoefficient( Z6[i],-1)
            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][1][7],1)
            Con62.SetCoefficient(X[i][2][0],1)
            S1=solver.IntVar(0.0, 1.0, "1S"+str(i))
            S2=solver.IntVar(0.0, 1.0, "2S"+str(i))
            S3=solver.IntVar(0.0, 1.0, "3S"+str(i))
            S4=solver.IntVar(0.0, 1.0, "4S"+str(i))
            S5=solver.IntVar(0.0, 1.0, "5S"+str(i))
            Con62.SetCoefficient(S1,-2)
            Con62p=solver.Constraint(-solver.infinity(),1)
            Con62p.SetCoefficient(X[i][6][1],1)
            Con62p.SetCoefficient(X[i][6][2],1)
            Con62p.SetCoefficient(X[i][6][3],1)
            Con62p.SetCoefficient(S1,1)
            Con63=solver.Constraint(0,solver.infinity())
            Con63.SetCoefficient(X[i][3][7],1)
            Con63.SetCoefficient(X[i][4][0],1)
            Con63.SetCoefficient(S3,-2)
            Con64=solver.Constraint(0,solver.infinity())
            Con64.SetCoefficient(X[i][4][7],1)
            Con64.SetCoefficient(X[i][5][0],1)
            Con64.SetCoefficient(S4,-2)
            Con644=solver.Constraint(0,solver.infinity())
            Con644.SetCoefficient(X[i][2][7],1)
            Con644.SetCoefficient(X[i][3][0],1)
            Con644.SetCoefficient(S2,-2)
            Con65=solver.Constraint(-solver.infinity(),1)
            Con65.SetCoefficient(S5,1)
            Con65.SetCoefficient(X[i][0][1],1)
            Con65.SetCoefficient(X[i][0][2],1)
            Con65.SetCoefficient(X[i][0][3],1)
            Con66=solver.Constraint(0,0)
            Con66.SetCoefficient(S1,1)
            Con66.SetCoefficient(S2,1)
            Con66.SetCoefficient(S3,1)
            Con66.SetCoefficient(S4,1)
            Con66.SetCoefficient(S5,1)
            Con66.SetCoefficient(Z3[i],-1)

            objective.SetCoefficient(X[i][1][5], Weight2)
            objective.SetCoefficient(X[i][1][6], Weight2)
            objective.SetCoefficient(X[i][3][4], Weight2)
            objective.SetCoefficient(X[i][2][4], Weight2)
            objective.SetCoefficient(X[i][0][3], -Weight25)

            if level <3:
                objective.SetCoefficient(X[i][1][4], -Weight25)
                objective.SetCoefficient(X[i][2][5], -Weight25)
                objective.SetCoefficient(X[i][2][6], -Weight25)
                objective.SetCoefficient(X[i][3][0], -Weight25)
                objective.SetCoefficient(X[i][4][0], -Weight25)
                objective.SetCoefficient(X[i][5][0], -Weight25)
                objective.SetCoefficient(X[i][6][1], -Weight25)
            elif(level >=3):
                objective.SetCoefficient(X[i][1][4], -Weight25)
                objective.SetCoefficient(X[i][2][5], -Weight25)
                objective.SetCoefficient(X[i][3][6], -Weight25)
                objective.SetCoefficient(X[i][4][0], -Weight25)
                objective.SetCoefficient(X[i][5][0], -Weight25)
                objective.SetCoefficient(X[i][6][0], -Weight25)

            p1=solver.IntVar(0.0, 1.0, "p1"+str(i))
            p2=solver.IntVar(0.0, 1.0, "p2"+str(i))
            p3=solver.IntVar(0.0, 1.0, "p3"+str(i))
            objective.SetCoefficient(p1, Weight2)
            objective.SetCoefficient(p2, Weight2)
            objective.SetCoefficient(p3, Weight2)
            Con71=solver.Constraint(-solver.infinity(),M)
            Con71.SetCoefficient(X[i][4][2],1)
            Con71.SetCoefficient(p1,-1)
            Con71.SetCoefficient(X[i][1][7],M)
            Con72=solver.Constraint(0,solver.infinity())
            Con72.SetCoefficient(p1,1)
            Con72.SetCoefficient(X[i][1][7],M)
            Con73=solver.Constraint(-solver.infinity(),M)
            Con73.SetCoefficient(X[i][5][2],1)
            Con73.SetCoefficient(p2,-1)
            Con73.SetCoefficient(X[i][2][7],M)
            Con74=solver.Constraint(0,solver.infinity())
            Con74.SetCoefficient(p2,1)
            Con74.SetCoefficient(X[i][2][7],M)
            Con75=solver.Constraint(-solver.infinity(),M)
            Con75.SetCoefficient(X[i][6][2],1)
            Con75.SetCoefficient(p3,-1)
            Con75.SetCoefficient(X[i][3][7],M)
            Con76=solver.Constraint(0,solver.infinity())
            Con76.SetCoefficient(p3,1)
            Con76.SetCoefficient(X[i][3][7],M)
            Consmin[i]=[Con71,Con72,Con73,Con74,Con75,Con76]
            xinlu[i]=solver.IntVar(-4.0, 4.0, "xinlu"+str(i))
            conxinlu[i]=solver.Constraint(3,3)
            conxinlu[i].SetCoefficient(X[i][1][0],1)
            conxinlu[i].SetCoefficient(X[i][2][0],1)
            conxinlu[i].SetCoefficient(X[i][3][0],1)
            conxinlu[i].SetCoefficient(X[i][4][0],1)
            conxinlu[i].SetCoefficient(X[i][5][0],1)
            conxinlu[i].SetCoefficient(X[i][6][0],1)
            conxinlu[i].SetCoefficient(xinlu[i],-1)
        elif stateinitial[i]==6:

            Con30=solver.Constraint(-solver.infinity(),1)
            Con30.SetCoefficient( X[i][2][7],1)
            Con30.SetCoefficient( X[i][1][7],1)
            Con30.SetCoefficient( X[i][0][7],1)

            if level >=3:
                Con30.SetCoefficient( X[i][3][7],1)
            Cons3[i]=Con30
            Con40=solver.Constraint(-solver.infinity(),0)
            Con40.SetCoefficient( X[i][0][0],1)
            Con40.SetCoefficient( X[i][2][1],1)
            Con40.SetCoefficient( X[i][2][2],1)
            Con40.SetCoefficient( X[i][2][3],1)
            Con40.SetCoefficient( X[i][6][4],1)
            Con40.SetCoefficient( X[i][6][5],1)
            Con40.SetCoefficient( X[i][6][6],1)
            Con40.SetCoefficient( X[i][0][7],-7)
            Con41=solver.Constraint(-solver.infinity(),0)
            Con41.SetCoefficient( X[i][1][0],1)
            Con41.SetCoefficient( X[i][3][1],1)
            Con41.SetCoefficient( X[i][3][2],1)
            Con41.SetCoefficient( X[i][3][3],1)
            Con41.SetCoefficient( X[i][1][7],-M)
            Con41.SetCoefficient( X[i][0][7],-M)
            Con42=solver.Constraint(-solver.infinity(),0)
            if level<3:
                Con42.SetCoefficient( X[i][3][0],1)
                Con42.SetCoefficient( X[i][2][0],1)
                Con42.SetCoefficient( X[i][4][1],1)
                Con42.SetCoefficient( X[i][4][2],1)
                Con42.SetCoefficient( X[i][4][3],1)
                Con42.SetCoefficient( X[i][5][1],1)
                Con42.SetCoefficient( X[i][5][2],1)
                Con42.SetCoefficient( X[i][5][3],1)
                Con42.SetCoefficient( X[i][0][7],-M)
                Con42.SetCoefficient( X[i][1][7],-M)
                Con42.SetCoefficient( X[i][2][7],-M)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][4][0],1)
                Con43.SetCoefficient( X[i][6][1],1)
                Con43.SetCoefficient( X[i][6][2],1)
                Con43.SetCoefficient( X[i][6][3],1)
                Con43.SetCoefficient( X[i][1][7],-M)
                Con43.SetCoefficient( X[i][2][7],-M)
                Con44=solver.Constraint(-solver.infinity(),0)
                Con44.SetCoefficient( X[i][5][0],1)
                Con44.SetCoefficient( X[i][2][7],-1)
                Con45=solver.Constraint(-solver.infinity(),0)
                Con45.SetCoefficient( X[i][6][0],1)
                Con45.SetCoefficient( X[i][6][7],-1)
                Con46=solver.Constraint(-solver.infinity(),0)
                Con46.SetCoefficient( X[i][6][7],1)
                Con46.SetCoefficient( X[i][0][7],-1)
                Cons4[i]=[Con40,Con41,Con42,Con43,Con44,Con45,Con46]
            elif level>=3:
                Con42.SetCoefficient( X[i][2][0],1)
                Con42.SetCoefficient( X[i][4][1],1)
                Con42.SetCoefficient( X[i][4][2],1)
                Con42.SetCoefficient( X[i][4][3],1)
                Con42.SetCoefficient( X[i][0][7],-M)
                Con42.SetCoefficient( X[i][1][7],-M)
                Con42.SetCoefficient( X[i][2][7],-M)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][3][0],1)
                Con43.SetCoefficient( X[i][5][1],1)
                Con43.SetCoefficient( X[i][5][2],1)
                Con43.SetCoefficient( X[i][5][3],1)
                Con43.SetCoefficient( X[i][1][7],-M)
                Con43.SetCoefficient( X[i][2][7],-M)
                Con43.SetCoefficient( X[i][0][7],-M)
                Con43.SetCoefficient( X[i][3][7],-M)
                Con44=solver.Constraint(-solver.infinity(),0)
                Con44.SetCoefficient( X[i][4][0],1)
                Con44.SetCoefficient( X[i][6][1],1)
                Con44.SetCoefficient( X[i][6][2],1)
                Con44.SetCoefficient( X[i][6][3],1)
                Con44.SetCoefficient( X[i][2][7],-M)
                Con44.SetCoefficient( X[i][1][7],-M)
                Con44.SetCoefficient( X[i][3][7],-M)
                Con45=solver.Constraint(-solver.infinity(),0)
                Con45.SetCoefficient( X[i][6][0],1)
                Con45.SetCoefficient( X[i][6][7],-1)
                Con45.SetCoefficient( X[i][3][7],-1)
                Con46=solver.Constraint(-solver.infinity(),0)
                Con46.SetCoefficient( X[i][6][7],1)
                Con46.SetCoefficient( X[i][0][7],-1)
                Con47=solver.Constraint(-solver.infinity(),0)
                Con47.SetCoefficient( X[i][5][0],1)
                Con47.SetCoefficient( X[i][2][7],-1)
                Con47.SetCoefficient( X[i][3][7],-1)
                Cons4[i]=[Con40,Con41,Con42,Con43,Con44,Con45,Con46,Con47]
            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][1][4],1)
            Con50.SetCoefficient( X[i][1][5],1)
            Con50.SetCoefficient( X[i][1][6],1)
            Con50.SetCoefficient( X[i][0][4],1)
            Con50.SetCoefficient( X[i][0][5],1)
            Con50.SetCoefficient( X[i][0][6],1)
            Con50.SetCoefficient( X[i][0][7],M)
            Con51=solver.Constraint(-solver.infinity(),M)
            Con51.SetCoefficient( X[i][1][4],1)
            Con51.SetCoefficient( X[i][1][5],1)
            Con51.SetCoefficient( X[i][1][6],1)
            Con51.SetCoefficient( X[i][1][7],M)
            Con52=solver.Constraint(-solver.infinity(),M)
            Con52.SetCoefficient( X[i][6][1],1)
            Con52.SetCoefficient( X[i][6][2],1)
            Con52.SetCoefficient( X[i][6][3],1)
            Con52.SetCoefficient( X[i][6][4],1)
            Con52.SetCoefficient( X[i][6][5],1)
            Con52.SetCoefficient( X[i][6][6],1)
            Con52.SetCoefficient( X[i][6][7],M)
            Cons5[i]=[Con50,Con51,Con52]
            if level >=3:
                Con50.SetCoefficient( X[i][2][4],1)
                Con50.SetCoefficient( X[i][2][5],1)
                Con50.SetCoefficient( X[i][2][6],1)
                Con51.SetCoefficient( X[i][2][4],1)
                Con51.SetCoefficient( X[i][2][5],1)
                Con51.SetCoefficient( X[i][2][6],1)
                Con53=solver.Constraint(-solver.infinity(),M)
                Con53.SetCoefficient( X[i][2][4],1)
                Con53.SetCoefficient( X[i][2][5],1)
                Con53.SetCoefficient( X[i][2][6],1)
                Con53.SetCoefficient( X[i][2][7],M)
                Cons5[i]=[Con50,Con51,Con52,Con53]
            S1=solver.IntVar(0.0, 1.0, "S1"+str(i))
            S2=solver.IntVar(0.0, 1.0, "S2"+str(i))
            S3=solver.IntVar(0.0, 1.0, "S3"+str(i))
            S4=solver.IntVar(0.0, 1.0, "S4"+str(i))
            Cona1=solver.Constraint(0,solver.infinity())
            Cona1.SetCoefficient(X[i][1][7],1)
            Cona1.SetCoefficient(S1,-1)
            Cona2=solver.Constraint(0,solver.infinity())
            Cona2.SetCoefficient(X[i][2][7],1)
            Cona2.SetCoefficient(S2,-1)
            Cona3=solver.Constraint(0,solver.infinity())
            Cona3.SetCoefficient(X[i][0][7],1)
            Cona3.SetCoefficient(S3,-1)
            Cona4=solver.Constraint(0,solver.infinity())
            Cona4.SetCoefficient(X[i][1][7],1)
            Cona4.SetCoefficient(S4,-1)

            S11=solver.IntVar(0.0, 1.0, "11S"+str(i))
            S12=solver.IntVar(0.0, 1.0, "21S"+str(i))
            S13=solver.IntVar(0.0, 1.0, "31S"+str(i))
            Con61=solver.Constraint(-solver.infinity(),M)
            Con61.SetCoefficient( S11,M)
            Con61.SetCoefficient( X[i][0][7],1)
            Con61.SetCoefficient( X[i][1][7],1)
            for j in range(prodnum+1):

                Con61.SetCoefficient( X[i][2][j],1)
            Con601=solver.Constraint(0,solver.infinity())
            Con601.SetCoefficient( X[i][0][7],1)
            Con601.SetCoefficient( X[i][5][1],1)
            Con601.SetCoefficient( X[i][5][2],1)
            Con601.SetCoefficient( X[i][5][3],1)
            Con601.SetCoefficient( S12,-2)
            Con603=solver.Constraint(0,solver.infinity())
            Con603.SetCoefficient( X[i][1][7],1)
            Con603.SetCoefficient( X[i][6][1],1)
            Con603.SetCoefficient( X[i][6][2],1)
            Con603.SetCoefficient( X[i][6][3],1)
            Con603.SetCoefficient( S13,-2)
            Con602=solver.Constraint(0,0)
            Con602.SetCoefficient( S11,1)
            Con602.SetCoefficient( S12,1)
            Con602.SetCoefficient( S13,1)
            Con602.SetCoefficient( Z6[i],-1)

            S1=solver.IntVar(0.0, 1.0, "1S"+str(i))
            S2=solver.IntVar(0.0, 1.0, "2S"+str(i))
            S3=solver.IntVar(0.0, 1.0, "3S"+str(i))
            S4=solver.IntVar(0.0, 1.0, "4S"+str(i))
            S5=solver.IntVar(0.0, 1.0, "5S"+str(i))
            Con620=solver.Constraint(0,solver.infinity())
            Con620.SetCoefficient(X[i][0][7],1)
            Con620.SetCoefficient(X[i][1][0],1)
            Con620.SetCoefficient(S1,-2)
            Con62p0=solver.Constraint(-solver.infinity(),1)
            Con62p0.SetCoefficient(X[i][5][1],1)
            Con62p0.SetCoefficient(X[i][5][2],1)
            Con62p0.SetCoefficient(X[i][5][3],1)
            Con62p0.SetCoefficient(S1,1)
            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][1][7],1)
            Con62.SetCoefficient(X[i][2][0],1)
            Con62.SetCoefficient(S2,-2)
            Con62p=solver.Constraint(-solver.infinity(),1)
            Con62p.SetCoefficient(X[i][6][1],1)
            Con62p.SetCoefficient(X[i][6][2],1)
            Con62p.SetCoefficient(X[i][6][3],1)
            Con62p.SetCoefficient(S2,1)
            Con63=solver.Constraint(0,solver.infinity())
            Con63.SetCoefficient(X[i][2][7],1)
            Con63.SetCoefficient(X[i][3][0],1)
            Con63.SetCoefficient(S3,-2)
            Con64=solver.Constraint(0,solver.infinity())
            Con64.SetCoefficient(X[i][3][7],1)
            Con64.SetCoefficient(X[i][4][0],1)
            Con64.SetCoefficient(S4,-2)
            Con66=solver.Constraint(0,0)
            Con66.SetCoefficient(S1,1)
            Con66.SetCoefficient(S2,1)
            Con66.SetCoefficient(S3,1)
            Con66.SetCoefficient(S4,1)
            Con66.SetCoefficient(Z3[i],-1)

            objective.SetCoefficient(X[i][0][5], Weight2)
            objective.SetCoefficient(X[i][0][6], Weight2)
            objective.SetCoefficient(X[i][1][4], Weight2)
            objective.SetCoefficient(X[i][2][4], Weight2)
            if level <3:
                objective.SetCoefficient(X[i][0][4], -Weight25)
                objective.SetCoefficient(X[i][1][5], -Weight25)
                objective.SetCoefficient(X[i][1][6], -Weight25)
                objective.SetCoefficient(X[i][2][0], -Weight25)
                objective.SetCoefficient(X[i][3][0], -Weight25)
                objective.SetCoefficient(X[i][4][0], -Weight25)
                objective.SetCoefficient(X[i][5][1], -Weight25)
                objective.SetCoefficient(X[i][6][2], -Weight25)
            elif(level >=3):
                objective.SetCoefficient(X[i][0][4], -Weight25)
                objective.SetCoefficient(X[i][1][5], -Weight25)
                objective.SetCoefficient(X[i][2][6], -Weight25)
                objective.SetCoefficient(X[i][3][0], -Weight25)
                objective.SetCoefficient(X[i][4][0], -Weight25)
                objective.SetCoefficient(X[i][5][0], -Weight25)
                objective.SetCoefficient(X[i][6][1], -Weight25)

            p0=solver.IntVar(0.0, 1.0, "p0"+str(i))
            p1=solver.IntVar(0.0, 1.0, "p1"+str(i))
            p2=solver.IntVar(0.0, 1.0, "p2"+str(i))
            p3=solver.IntVar(0.0, 1.0, "p3"+str(i))
            p4=solver.IntVar(0.0, 1.0, "p4"+str(i))
            p5=solver.IntVar(0.0, 1.0, "p5"+str(i))
            objective.SetCoefficient(p0, Weight2)
            objective.SetCoefficient(p1, Weight2)
            objective.SetCoefficient(p2, Weight2)
            objective.SetCoefficient(p3, Weight2)
            objective.SetCoefficient(p4, Weight2)

            Con701=solver.Constraint(-solver.infinity(),M)
            Con701.SetCoefficient(X[i][3][2],1)
            Con701.SetCoefficient(p0,-1)
            Con701.SetCoefficient(X[i][0][7],M)
            Con702=solver.Constraint(0,solver.infinity())
            Con702.SetCoefficient(p0,1)
            Con702.SetCoefficient(X[i][0][7],M)
            Con71=solver.Constraint(-solver.infinity(),M)
            Con71.SetCoefficient(X[i][4][2],1)
            Con71.SetCoefficient(p1,-1)
            Con71.SetCoefficient(X[i][1][7],M)
            Con72=solver.Constraint(0,solver.infinity())
            Con72.SetCoefficient(p1,1)
            Con72.SetCoefficient(X[i][1][7],M)
            Con73=solver.Constraint(-solver.infinity(),M)
            Con73.SetCoefficient(X[i][5][2],1)
            Con73.SetCoefficient(p2,-1)
            Con73.SetCoefficient(X[i][2][7],M)
            Con74=solver.Constraint(0,solver.infinity())
            Con74.SetCoefficient(p2,1)
            Con74.SetCoefficient(X[i][2][7],M)
            Con75=solver.Constraint(-solver.infinity(),M)
            Con75.SetCoefficient(X[i][6][5],1)
            Con75.SetCoefficient(p3,-1)
            Con75.SetCoefficient(X[i][0][7],M)
            Con76=solver.Constraint(0,solver.infinity())
            Con76.SetCoefficient(p3,1)
            Con76.SetCoefficient(X[i][0][7],M)
            Con77=solver.Constraint(-solver.infinity(),M)
            Con77.SetCoefficient(X[i][6][6],1)
            Con77.SetCoefficient(p4,-1)
            Con77.SetCoefficient(X[i][0][7],M)
            Con78=solver.Constraint(0,solver.infinity())
            Con78.SetCoefficient(p4,1)
            Con78.SetCoefficient(X[i][0][7],M)
            Consmin[i]=[Con701,Con702,Con71,Con72,Con73,Con74,Con75,Con76,Con77,Con78]
            if level>=3:
                objective.SetCoefficient(p5, Weight2)
                Con79=solver.Constraint(-solver.infinity(),M)
                Con79.SetCoefficient(X[i][6][2],1)
                Con79.SetCoefficient(p5,-1)
                Con79.SetCoefficient(X[i][3][7],M)
                Con710=solver.Constraint(0,solver.infinity())
                Con710.SetCoefficient(p5,1)
                Con710.SetCoefficient(X[i][3][7],M)
                Consmin[i]=[Con701,Con702,Con71,Con72,Con73,Con74,Con75,Con76,Con77,Con78,Con79,Con710]
            xinlu[i]=solver.IntVar(-4.0, 4.0, "xinlu"+str(i))
            conxinlu[i]=solver.Constraint(3,3)
            conxinlu[i].SetCoefficient(X[i][0][0],1)
            conxinlu[i].SetCoefficient(X[i][1][0],1)
            conxinlu[i].SetCoefficient(X[i][2][0],1)
            conxinlu[i].SetCoefficient(X[i][3][0],1)
            conxinlu[i].SetCoefficient(X[i][4][0],1)
            conxinlu[i].SetCoefficient(X[i][5][0],1)
            conxinlu[i].SetCoefficient(X[i][6][0],1)
            conxinlu[i].SetCoefficient(xinlu[i],-1)
        elif stateinitial[i]==7:
            Con30=solver.Constraint(-solver.infinity(),1)
            Con30.SetCoefficient( X[i][1][7],1)
            Con30.SetCoefficient( X[i][0][7],1)
            if (level>=3):
                Con30.SetCoefficient( X[i][2][7],1)
            Cons3[i]=Con30
            Con41=solver.Constraint(-solver.infinity(),0)
            Con41.SetCoefficient( X[i][0][0],1)
            Con41.SetCoefficient( X[i][2][1],1)
            Con41.SetCoefficient( X[i][2][2],1)
            Con41.SetCoefficient( X[i][2][3],1)
            Con41.SetCoefficient( X[i][6][4],1)
            Con41.SetCoefficient( X[i][6][5],1)
            Con41.SetCoefficient( X[i][6][6],1)
            Con41.SetCoefficient( X[i][0][7],-M)

            Con42=solver.Constraint(-solver.infinity(),0)
            if (level<3):
                Con42.SetCoefficient( X[i][1][0],1)
                Con42.SetCoefficient( X[i][2][0],1)
                Con42.SetCoefficient( X[i][3][0],1)
                Con42.SetCoefficient( X[i][3][1],1)
                Con42.SetCoefficient( X[i][3][2],1)
                Con42.SetCoefficient( X[i][3][3],1)
                Con42.SetCoefficient( X[i][4][1],1)
                Con42.SetCoefficient( X[i][4][2],1)
                Con42.SetCoefficient( X[i][4][3],1)
                Con42.SetCoefficient( X[i][5][1],1)
                Con42.SetCoefficient( X[i][5][2],1)
                Con42.SetCoefficient( X[i][5][3],1)
                Con42.SetCoefficient( X[i][0][7],-M)
                Con42.SetCoefficient( X[i][1][7],-M)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][4][0],1)
                Con43.SetCoefficient( X[i][6][1],1)
                Con43.SetCoefficient( X[i][6][2],1)
                Con43.SetCoefficient( X[i][6][3],1)
                Con43.SetCoefficient( X[i][1][7],-M)
                Con44=solver.Constraint(-solver.infinity(),0)
                Con44.SetCoefficient( X[i][6][0],1)
                Con44.SetCoefficient( X[i][6][7],-1)
                Con45=solver.Constraint(-solver.infinity(),0)
                Con45.SetCoefficient( X[i][6][7],1)
                Con45.SetCoefficient( X[i][0][7],-1)
                Cons4[i]=[Con41,Con42,Con43,Con44,Con45]
            elif (level>=3):
                Con42.SetCoefficient( X[i][1][0],1)
                Con42.SetCoefficient( X[i][3][1],1)
                Con42.SetCoefficient( X[i][3][2],1)
                Con42.SetCoefficient( X[i][3][3],1)
                Con42.SetCoefficient( X[i][0][7],-M)
                Con42.SetCoefficient( X[i][1][7],-M)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][4][1],1)
                Con43.SetCoefficient( X[i][4][2],1)
                Con43.SetCoefficient( X[i][4][3],1)
                Con43.SetCoefficient( X[i][5][1],1)
                Con43.SetCoefficient( X[i][5][2],1)
                Con43.SetCoefficient( X[i][5][3],1)
                Con43.SetCoefficient( X[i][2][0],1)
                Con43.SetCoefficient( X[i][3][0],1)
                Con43.SetCoefficient( X[i][1][7],-M)
                Con43.SetCoefficient( X[i][0][7],-M)
                Con43.SetCoefficient( X[i][2][7],-M)
                Con44=solver.Constraint(-solver.infinity(),0)
                Con44.SetCoefficient( X[i][6][0],1)
                Con44.SetCoefficient( X[i][6][7],-1)
                Con45=solver.Constraint(-solver.infinity(),0)
                Con45.SetCoefficient( X[i][6][7],1)
                Con45.SetCoefficient( X[i][0][7],-1)
                Con46=solver.Constraint(-solver.infinity(),0)
                Con46.SetCoefficient( X[i][5][0],1)
                Con46.SetCoefficient( X[i][2][7],-1)
                Con47=solver.Constraint(-solver.infinity(),0)
                Con47.SetCoefficient( X[i][4][0],1)
                Con47.SetCoefficient( X[i][6][1],1)
                Con47.SetCoefficient( X[i][6][2],1)
                Con47.SetCoefficient( X[i][6][3],1)
                Con47.SetCoefficient( X[i][1][7],-M)
                Con47.SetCoefficient( X[i][2][7],-M)
                Cons4[i]=[Con41,Con42,Con43,Con44,Con45,Con46,Con47]
            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][0][4],1)
            Con50.SetCoefficient( X[i][0][5],1)
            Con50.SetCoefficient( X[i][0][6],1)
            Con50.SetCoefficient( X[i][0][7],M)
            Con51=solver.Constraint(-solver.infinity(),M)
            Con51.SetCoefficient( X[i][6][1],1)
            Con51.SetCoefficient( X[i][6][2],1)
            Con51.SetCoefficient( X[i][6][3],1)
            Con51.SetCoefficient( X[i][6][4],1)
            Con51.SetCoefficient( X[i][6][5],1)
            Con51.SetCoefficient( X[i][6][6],1)
            Con51.SetCoefficient( X[i][6][7],M)
            Cons5[i]=[Con50,Con51]
            if level >=3:
                Con50.SetCoefficient( X[i][1][4],1)
                Con50.SetCoefficient( X[i][1][5],1)
                Con50.SetCoefficient( X[i][1][6],1)
                Con51.SetCoefficient( X[i][1][4],1)
                Con51.SetCoefficient( X[i][1][5],1)
                Con51.SetCoefficient( X[i][1][6],1)
                Con52=solver.Constraint(-solver.infinity(),M)
                Con52.SetCoefficient( X[i][1][4],1)
                Con52.SetCoefficient( X[i][1][5],1)
                Con52.SetCoefficient( X[i][1][6],1)
                Con52.SetCoefficient( X[i][1][7],M)
                Cons5[i]=[Con50,Con51,Con52]


            S3=solver.IntVar(0.0, 1.0, "S3"+str(i))
            S4=solver.IntVar(0.0, 1.0, "S4"+str(i))
            Cona3=solver.Constraint(0,solver.infinity())
            Cona3.SetCoefficient(X[i][0][7],1)
            Cona3.SetCoefficient(S3,-1)
            Cona4=solver.Constraint(0,solver.infinity())
            Cona4.SetCoefficient(X[i][1][7],1)
            Cona4.SetCoefficient(S4,-1)

            S11=solver.IntVar(0.0, 1.0, "11S"+str(i))
            S12=solver.IntVar(0.0, 1.0, "21S"+str(i))
            S13=solver.IntVar(0.0, 1.0, "31S"+str(i))
            Con61=solver.Constraint(-solver.infinity(),M)
            Con61.SetCoefficient( S11,M)
            Con61.SetCoefficient( X[i][0][7],1)
            for j in range(prodnum+1):

                Con61.SetCoefficient( X[i][1][j],1)
            Con601=solver.Constraint(0,solver.infinity())
            Con601.SetCoefficient( X[i][0][7],1)
            Con601.SetCoefficient( X[i][5][1],1)
            Con601.SetCoefficient( X[i][5][2],1)
            Con601.SetCoefficient( X[i][5][3],1)
            Con601.SetCoefficient( S12,-2)
            Con603=solver.Constraint(0,solver.infinity())
            Con603.SetCoefficient( X[i][1][7],1)
            Con603.SetCoefficient( X[i][6][1],1)
            Con603.SetCoefficient( X[i][6][2],1)
            Con603.SetCoefficient( X[i][6][3],1)
            Con603.SetCoefficient( S13,-2)
            Con602=solver.Constraint(0,0)
            Con602.SetCoefficient( S11,1)
            Con602.SetCoefficient( S12,1)
            Con602.SetCoefficient( S13,1)
            Con602.SetCoefficient( Z6[i],-1)

            S1=solver.IntVar(0.0, 1.0, "1S"+str(i))
            S2=solver.IntVar(0.0, 1.0, "2S"+str(i))
            S3=solver.IntVar(0.0, 1.0, "3S"+str(i))
            Con620=solver.Constraint(0,solver.infinity())
            Con620.SetCoefficient(X[i][0][7],1)
            Con620.SetCoefficient(X[i][1][0],1)
            Con620.SetCoefficient(S1,-2)
            Con62p0=solver.Constraint(-solver.infinity(),1)
            Con62p0.SetCoefficient(X[i][5][1],1)
            Con62p0.SetCoefficient(X[i][5][2],1)
            Con62p0.SetCoefficient(X[i][5][3],1)
            Con62p0.SetCoefficient(S1,1)
            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][1][7],1)
            Con62.SetCoefficient(X[i][2][0],1)
            Con62.SetCoefficient(S2,-2)
            Con62p=solver.Constraint(-solver.infinity(),1)
            Con62p.SetCoefficient(X[i][6][1],1)
            Con62p.SetCoefficient(X[i][6][2],1)
            Con62p.SetCoefficient(X[i][6][3],1)
            Con62p.SetCoefficient(S2,1)
            Con63=solver.Constraint(0,solver.infinity())
            Con63.SetCoefficient(X[i][2][7],1)
            Con63.SetCoefficient(X[i][3][0],1)
            Con63.SetCoefficient(S3,-2)
            Con66=solver.Constraint(0,0)
            Con66.SetCoefficient(S1,1)
            Con66.SetCoefficient(S2,1)
            Con66.SetCoefficient(S3,1)
            Con66.SetCoefficient(Z3[i],-1)

            p0=solver.IntVar(0.0, 1.0, "p0"+str(i))
            p1=solver.IntVar(0.0, 1.0, "p1"+str(i))
            p3=solver.IntVar(0.0, 1.0, "p3"+str(i))
            p4=solver.IntVar(0.0, 1.0, "p4"+str(i))
            p5=solver.IntVar(0.0, 1.0, "p5"+str(i))
            objective.SetCoefficient(p0, Weight2)
            objective.SetCoefficient(p1, Weight2)
            objective.SetCoefficient(p3, Weight2)
            objective.SetCoefficient(p4, Weight2)
            objective.SetCoefficient(X[i][1][4], Weight2)
            objective.SetCoefficient(X[i][0][4], Weight2)
            if level <3:
                objective.SetCoefficient(X[i][0][5], -Weight25)
                objective.SetCoefficient(X[i][0][6], -Weight25)
                objective.SetCoefficient(X[i][1][0], -Weight25)
                objective.SetCoefficient(X[i][2][0], -Weight25)
                objective.SetCoefficient(X[i][3][0], -Weight25)
                objective.SetCoefficient(X[i][4][1], -Weight25)
                objective.SetCoefficient(X[i][5][2], -Weight25)
                objective.SetCoefficient(X[i][6][3], -Weight25)
            elif(level >=3):
                objective.SetCoefficient(X[i][0][4], -Weight25)
                objective.SetCoefficient(X[i][1][5], -Weight25)
                objective.SetCoefficient(X[i][1][6], -Weight25)
                objective.SetCoefficient(X[i][2][0], -Weight25)
                objective.SetCoefficient(X[i][3][0], -Weight25)
                objective.SetCoefficient(X[i][4][0], -Weight25)
                objective.SetCoefficient(X[i][5][1], -Weight25)
                objective.SetCoefficient(X[i][6][2], -Weight25)
            Con701=solver.Constraint(-solver.infinity(),M)
            Con701.SetCoefficient(X[i][3][2],1)
            Con701.SetCoefficient(p0,-1)
            Con701.SetCoefficient(X[i][0][7],M)
            Con702=solver.Constraint(0,solver.infinity())
            Con702.SetCoefficient(p0,1)
            Con702.SetCoefficient(X[i][0][7],M)
            Con71=solver.Constraint(-solver.infinity(),M)
            Con71.SetCoefficient(X[i][4][2],1)
            Con71.SetCoefficient(p1,-1)
            Con71.SetCoefficient(X[i][1][7],M)
            Con72=solver.Constraint(0,solver.infinity())
            Con72.SetCoefficient(p1,1)
            Con72.SetCoefficient(X[i][1][7],M)
            Con75=solver.Constraint(-solver.infinity(),M)
            Con75.SetCoefficient(X[i][6][5],1)
            Con75.SetCoefficient(p3,-1)
            Con75.SetCoefficient(X[i][0][7],M)
            Con76=solver.Constraint(0,solver.infinity())
            Con76.SetCoefficient(p3,1)
            Con76.SetCoefficient(X[i][0][7],M)
            Con77=solver.Constraint(-solver.infinity(),M)
            Con77.SetCoefficient(X[i][6][6],1)
            Con77.SetCoefficient(p4,-1)
            Con77.SetCoefficient(X[i][0][7],M)
            Con78=solver.Constraint(0,solver.infinity())
            Con78.SetCoefficient(p4,1)
            Con78.SetCoefficient(X[i][0][7],M)
            Consmin[i]=[Con701,Con702,Con71,Con72,Con75,Con76,Con77,Con78]
            if level>=3:
                objective.SetCoefficient(p5, Weight2)
                Con79=solver.Constraint(-solver.infinity(),M)
                Con79.SetCoefficient(X[i][5][2],1)
                Con79.SetCoefficient(p5,-1)
                Con79.SetCoefficient(X[i][2][7],M)
                Con710=solver.Constraint(0,solver.infinity())
                Con710.SetCoefficient(p5,1)
                Con710.SetCoefficient(X[i][2][7],M)
        elif stateinitial[i]==8:

            if(level<3):
                Conss=solver.Constraint(1,1)
                Conss.SetCoefficient(X[i][0][7],1)
                Con42=solver.Constraint(-solver.infinity(),0)
                Con42.SetCoefficient( X[i][0][0],1)
                Con42.SetCoefficient( X[i][1][0],1)
                Con42.SetCoefficient( X[i][2][0],1)
                Con42.SetCoefficient( X[i][3][0],1)
                Con42.SetCoefficient( X[i][2][1],1)
                Con42.SetCoefficient( X[i][2][2],1)
                Con42.SetCoefficient( X[i][2][3],1)
                Con42.SetCoefficient( X[i][3][1],1)
                Con42.SetCoefficient( X[i][3][2],1)
                Con42.SetCoefficient( X[i][3][3],1)
                Con42.SetCoefficient( X[i][4][1],1)
                Con42.SetCoefficient( X[i][4][2],1)
                Con42.SetCoefficient( X[i][4][3],1)
                Con42.SetCoefficient( X[i][5][1],1)
                Con42.SetCoefficient( X[i][5][2],1)
                Con42.SetCoefficient( X[i][5][3],1)
                Con42.SetCoefficient( X[i][6][4],1)
                Con42.SetCoefficient( X[i][6][5],1)
                Con42.SetCoefficient( X[i][6][6],1)
                Con42.SetCoefficient( X[i][0][7],-M)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][6][0],1)
                Con43.SetCoefficient( X[i][6][7],-1)
                Con44=solver.Constraint(-solver.infinity(),0)
                Con44.SetCoefficient( X[i][6][7],1)
                Con44.SetCoefficient( X[i][0][7],-1)
                Cons4[i]=[Con42,Con43,Con44]
            elif level>=3:
                Conss=solver.Constraint(-solver.infinity(),1)
                Conss.SetCoefficient(X[i][0][7],1)
                Conss.SetCoefficient(X[i][1][7],1)
                Con42=solver.Constraint(-solver.infinity(),0)
                Con42.SetCoefficient( X[i][0][0],1)
                Con42.SetCoefficient( X[i][2][1],1)
                Con42.SetCoefficient( X[i][2][2],1)
                Con42.SetCoefficient( X[i][2][3],1)
                Con42.SetCoefficient( X[i][6][4],1)
                Con42.SetCoefficient( X[i][6][5],1)
                Con42.SetCoefficient( X[i][6][6],1)
                Con42.SetCoefficient( X[i][0][7],-M)
                Con43=solver.Constraint(-solver.infinity(),0)
                Con43.SetCoefficient( X[i][1][0],1)
                Con43.SetCoefficient( X[i][2][0],1)
                Con43.SetCoefficient( X[i][3][0],1)
                Con43.SetCoefficient( X[i][3][1],1)
                Con43.SetCoefficient( X[i][3][2],1)
                Con43.SetCoefficient( X[i][3][3],1)
                Con43.SetCoefficient( X[i][4][1],1)
                Con43.SetCoefficient( X[i][4][2],1)
                Con43.SetCoefficient( X[i][4][3],1)
                Con43.SetCoefficient( X[i][5][1],1)
                Con43.SetCoefficient( X[i][5][2],1)
                Con43.SetCoefficient( X[i][5][3],1)
                Con43.SetCoefficient( X[i][0][7],-M)
                Con43.SetCoefficient( X[i][1][7],-M)
                Con44=solver.Constraint(-solver.infinity(),0)
                Con44.SetCoefficient( X[i][6][7],1)
                Con44.SetCoefficient( X[i][0][7],-1)
                Con46=solver.Constraint(-solver.infinity(),0)
                Con46.SetCoefficient( X[i][6][0],1)
                Con46.SetCoefficient( X[i][6][7],-1)
                Con47=solver.Constraint(-solver.infinity(),0)
                Con47.SetCoefficient( X[i][4][0],1)
                Con47.SetCoefficient( X[i][6][1],1)
                Con47.SetCoefficient( X[i][6][2],1)
                Con47.SetCoefficient( X[i][6][3],1)
                Con47.SetCoefficient( X[i][1][7],-1)
                Cons4[i]=[Con42,Con43,Con44,Con46,Con47]
            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][6][4],1)
            Con50.SetCoefficient( X[i][6][5],1)
            Con50.SetCoefficient( X[i][6][6],1)
            Con50.SetCoefficient( X[i][6][7],M)
            Cons5[i]=[Con50]
            if level>=3:
                Con51=solver.Constraint(-solver.infinity(),M)
                Con51.SetCoefficient( X[i][0][4],1)
                Con51.SetCoefficient( X[i][0][5],1)
                Con51.SetCoefficient( X[i][0][6],1)
                Con51.SetCoefficient( X[i][0][7],M)
                Cons5[i]=[Con50,Con51]

            S11=solver.IntVar(0.0, 1.0, "11S"+str(i))
            S12=solver.IntVar(0.0, 1.0, "21S"+str(i))
            S13=solver.IntVar(0.0, 1.0, "31S"+str(i))

            Con601=solver.Constraint(0,solver.infinity())
            Con601.SetCoefficient( X[i][0][7],1)
            Con601.SetCoefficient( X[i][5][1],1)
            Con601.SetCoefficient( X[i][5][2],1)
            Con601.SetCoefficient( X[i][5][3],1)
            Con601.SetCoefficient( S11,-2)
            Con603=solver.Constraint(0,solver.infinity())
            Con603.SetCoefficient( X[i][1][7],1)
            Con603.SetCoefficient( X[i][6][1],1)
            Con603.SetCoefficient( X[i][6][2],1)
            Con603.SetCoefficient( X[i][6][3],1)
            Con603.SetCoefficient( S12,-2)
            Con604=solver.Constraint(-solver.infinity(),1)
            Con604.SetCoefficient(S13,1)
            for  j in range(prodnum+1):
                Con604.SetCoefficient(X[i][0][j],1)

            Con602=solver.Constraint(0,0)
            Con602.SetCoefficient( S11,1)
            Con602.SetCoefficient( S12,1)
            Con602.SetCoefficient( S13,1)
            Con602.SetCoefficient( Z6[i],-1)

            S1=solver.IntVar(0.0, 1.0, "1S"+str(i))
            S2=solver.IntVar(0.0, 1.0, "2S"+str(i))
            Con620=solver.Constraint(0,solver.infinity())
            Con620.SetCoefficient(X[i][0][7],1)
            Con620.SetCoefficient(X[i][1][0],1)
            Con620.SetCoefficient(S1,-2)
            Con62p0=solver.Constraint(-solver.infinity(),1)
            Con62p0.SetCoefficient(X[i][5][1],1)
            Con62p0.SetCoefficient(X[i][5][2],1)
            Con62p0.SetCoefficient(X[i][5][3],1)
            Con62p0.SetCoefficient(S1,1)
            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][1][7],1)
            Con62.SetCoefficient(X[i][2][0],1)
            Con62.SetCoefficient(S2,-2)
            Con62p=solver.Constraint(-solver.infinity(),1)
            Con62p.SetCoefficient(X[i][6][1],1)
            Con62p.SetCoefficient(X[i][6][2],1)
            Con62p.SetCoefficient(X[i][6][3],1)
            Con62p.SetCoefficient(S2,1)
            Con66=solver.Constraint(0,0)
            Con66.SetCoefficient(S1,1)
            Con66.SetCoefficient(S2,1)
            Con66.SetCoefficient(Z3[i],-1)

            objective.SetCoefficient(X[i][3][2], Weight2)
            objective.SetCoefficient(X[i][6][6], Weight2)
            objective.SetCoefficient(X[i][6][5], Weight2)
            objective.SetCoefficient(X[i][0][4], Weight2)
            if level >=3:
                objective.SetCoefficient(X[i][0][5], -Weight25)
                objective.SetCoefficient(X[i][0][6], -Weight25)
                objective.SetCoefficient(X[i][1][0], -Weight25)
                objective.SetCoefficient(X[i][2][0], -Weight25)
                objective.SetCoefficient(X[i][3][0], -Weight25)
                objective.SetCoefficient(X[i][4][1], -Weight25)
                objective.SetCoefficient(X[i][5][2], -Weight25)
                objective.SetCoefficient(X[i][6][3], -Weight25)
            else:
                objective.SetCoefficient(X[i][0][0], -Weight25)
                objective.SetCoefficient(X[i][1][0], -Weight25)
                objective.SetCoefficient(X[i][2][0], -Weight25)
                objective.SetCoefficient(X[i][3][1], -Weight25)
                objective.SetCoefficient(X[i][4][2], -Weight25)
                objective.SetCoefficient(X[i][5][3], -Weight25)
                objective.SetCoefficient(X[i][6][4], -Weight25)
            p1=solver.IntVar(0.0, 1.0, "p1"+str(i))
            if (level>=3):
                objective.SetCoefficient(p1, Weight2)
                Con79=solver.Constraint(-solver.infinity(),M)
                Con79.SetCoefficient(X[i][4][2],1)
                Con79.SetCoefficient(p1,-1)
                Con79.SetCoefficient(X[i][1][7],M)
                Con710=solver.Constraint(0,solver.infinity())
                Con710.SetCoefficient(p1,1)
                Con710.SetCoefficient(X[i][1][7],M)
        elif stateinitial[i]==9:

            Conss=solver.Constraint(1,1)
            Conss.SetCoefficient(X[i][0][7],1)
            Con43=solver.Constraint(-solver.infinity(),0)
            Con43.SetCoefficient( X[i][6][0],1)
            Con43.SetCoefficient( X[i][6][7],-1)
            Cons4[i]=[Conss,Con43]
            Con50=solver.Constraint(-solver.infinity(),M)
            Con50.SetCoefficient( X[i][6][4],1)
            Con50.SetCoefficient( X[i][6][5],1)
            Con50.SetCoefficient( X[i][6][6],1)
            Con50.SetCoefficient( X[i][6][7],M)
            Cons5[i]=[Con50]


            Con611=solver.Constraint(-solver.infinity(),0)
            Con611.SetCoefficient(Z6[i],2)
            Con611.SetCoefficient(X[i][0][7],-1)
            for j in range(prodnum+1):
                Con611.SetCoefficient(X[i][5][j],-1)
            Con62=solver.Constraint(0,solver.infinity())
            Con62.SetCoefficient(X[i][0][7],1)
            Con62.SetCoefficient(X[i][1][0],1)
            Con62.SetCoefficient(Z3[i],-2)
            Con63=solver.Constraint(-solver.infinity(),1)
            Con63.SetCoefficient(X[i][5][1],1)
            Con63.SetCoefficient(X[i][5][2],1)
            Con63.SetCoefficient(X[i][5][3],1)
            Con63.SetCoefficient(Z3[i],1)

            objective.SetCoefficient(X[i][3][2], Weight2)
            objective.SetCoefficient(X[i][6][6], Weight2)
            objective.SetCoefficient(X[i][6][5], Weight2)
            objective.SetCoefficient(X[i][0][0], -Weight25)
            objective.SetCoefficient(X[i][1][0], -Weight25)
            objective.SetCoefficient(X[i][2][0], -Weight25)
            objective.SetCoefficient(X[i][3][1], -Weight25)
            objective.SetCoefficient(X[i][4][2], -Weight25)
            objective.SetCoefficient(X[i][5][3], -Weight25)
            objective.SetCoefficient(X[i][6][4], -Weight25)
            p1=solver.IntVar(0.0, 1.0, "p1"+str(i))
            if (level>=3):
                objective.SetCoefficient(p1, Weight2)
                Con79=solver.Constraint(-solver.infinity(),M)
                Con79.SetCoefficient(X[i][4][2],1)
                Con79.SetCoefficient(p1,-1)
                Con79.SetCoefficient(X[i][1][7],M)
                Con710=solver.Constraint(0,solver.infinity())
                Con710.SetCoefficient(p1,1)
                Con710.SetCoefficient(X[i][1][7],M)

    df_final=pd.DataFrame(columns=["\u8d77\u59cb\u5708\u6b21","\u751f\u4ea7\u987a\u5e8f"])
    df=pd.DataFrame(columns=["\u521d\u59cb\u5708\u6b21","\u7b2c1\u5708","\u7b2c2\u5708","\u7b2c3\u5708","\u7b2c4\u5708","\u7b2c5\u5708","\u7b2c6\u5708","\u7b2c7\u5708","\u7b2c8\u5708"])
    dt=pd.DataFrame(columns=["\u521d\u59cb\u5708\u6b21","\u7b2c1\u5708","\u7b2c2\u5708","\u7b2c3\u5708","\u7b2c4\u5708","\u7b2c5\u5708","\u7b2c6\u5708","\u7b2c7\u5708","\u7b2c8\u5708"])
    dpici=pd.DataFrame(columns=["\u521d\u59cb\u5708\u6b21","\u7b2c1\u5708","\u7b2c2\u5708","\u7b2c3\u5708","\u7b2c4\u5708","\u7b2c5\u5708","\u7b2c6\u5708","\u7b2c7\u5708","\u7b2c8\u5708"])
    Cons151=[[] for i in range(guonum)]
    Cons152=[[] for i in range(guonum)]
    for l in range(guonum):
        Cons151[l]=solver.Constraint(-solver.infinity(),M)
        Cons152[l]=solver.Constraint(0,solver.infinity())
        for i in range(5):
            Cons151[l].SetCoefficient(X[l][i][7],1)
        Cons151[l].SetCoefficient(Y[l][4][0],M)
        Cons151[l].SetCoefficient(Y[l][4][1],M)
        Cons151[l].SetCoefficient(Y[l][4][2],M)
        Cons151[l].SetCoefficient(Y[l][4][3],M)
        Cons151[l].SetCoefficient(p[l],-1)
        Cons152[l].SetCoefficient(Y[l][4][0],M)
        Cons152[l].SetCoefficient(Y[l][4][1],M)
        Cons152[l].SetCoefficient(Y[l][4][2],M)
        Cons152[l].SetCoefficient(Y[l][4][3],M)
        Cons152[l].SetCoefficient(p[l],1)

    for l in range(guonum):

        objective.SetCoefficient(Y[l][5][0],M)
        objective.SetCoefficient(Y[l][5][1],M)
        objective.SetCoefficient(Y[l][5][2],M)
        objective.SetCoefficient(Y[l][5][3],M)
        objective.SetCoefficient(Y[l][5][4],0.5*M)
        objective.SetCoefficient(Y[l][5][5],0.5*M)
        objective.SetCoefficient(Y[l][5][6],0.5*M)
        objective.SetCoefficient(Y[l][6][0],2*M)
        objective.SetCoefficient(Y[l][6][1],2*M)
        objective.SetCoefficient(Y[l][6][2],2*M)
        objective.SetCoefficient(Y[l][6][3],2*M)
        objective.SetCoefficient(Y[l][6][4],2.5*M)
        objective.SetCoefficient(Y[l][6][5],2.5*M)
        objective.SetCoefficient(Y[l][6][6],2.5*M)

        for i in range(maxquanci):
            objective.SetCoefficient(X[l][i][7], Weight3)
    objective.SetMinimization()

    solver.SetTimeLimit(180000)
    result_status = solver.Solve()

    if( result_status == pywraplp.Solver.OPTIMAL and solver.VerifySolution(1e-7, True)):
        print("Solution Found!!")
        print('Number of variables =', solver.NumVariables())
        print('Number of constraints =', solver.NumConstraints())

        for l in range(guonum):
            d={}
            d['\u521d\u59cb\u5708\u6b21']=stateinitial[l]
            t={}
            t['\u521d\u59cb\u5708\u6b21']=stateinitial[l]
            pici={}
            pici['\u521d\u59cb\u5708\u6b21']=stateinitial[l]


            shengchanshunxu=[]
            index=1
            totaltime=0
            for i in range(maxquanci):
                for j in range(prodnum,-1,-1):

                    if(X[l][i][j].solution_value()>0):
                        totaltime+=lutime[j]
                        d["\u7b2c"+str(index)+"\u5708"]=prodname[j]
                        t["\u7b2c"+str(index)+"\u5708"]=totaltime
                        if(Y[l][i][j].solution_value()>0):
                            pici["\u7b2c"+str(index)+"\u5708"]=1
                            if split==True:
                                pici["\u7b2c"+str(index)+"\u5708"]=2

                        elif  j==prodnum :
                            pici["\u7b2c"+str(index)+"\u5708"]=0
                        else:
                            pici["\u7b2c"+str(index)+"\u5708"]=2

                        index+=1
                        shengchanshunxu.append(prodname[j])

            df_final.loc[l+1]=[stateinitial[l],shengchanshunxu]
            for i in range(index,9):
                d["\u7b2c"+str(i)+"\u5708"]=""
                t["\u7b2c"+str(i)+"\u5708"]=""
                pici["\u7b2c"+str(i)+"\u5708"]=""
            df.loc[l+1]=d
            dt.loc[l+1]=t
            dpici.loc[l+1]=pici

        index=3
        while(index<9):
            flag=False
            i=0
            while (i<  len(stateinitial)):
                if dpici.iloc[i,index]==2:
                    for index2 in range(3,9):
                        for i2 in range(len(stateinitial)):
                            if dpici.iloc[i2,index2]==1 and dt.iloc[i2,index2]>dt.iloc[i,index] and df.iloc[i,index]==df.iloc[i2,index2]:
                                dpici.iloc[i2,index2]=2
                                dpici.iloc[i,index]=1
                                flag=True
                                break
                        if flag==True:
                            break
                if flag==True:
                    i=0
                    break
                i+=1
            if flag==True:
                index=3
                continue
            index+=1

        print('Optimal objective value = %.2f' % solver.Objective().Value())
        jieshuquanci=[0 for i in range(guonum)]
        for i in range(guonum):
            count=stateinitial[i]
            for j in range(1,len(df.iloc[i,:])):
                if df.iloc[i,j]=='\u5364\u6c34':
                    count=0
                elif df.iloc[i,j]=="":
                    continue
                else:
                    count+=1

            jieshuquanci[i]=count

        return True,dpici,dt,df,jieshuquanci
    else:
        print("\u65e0\u89e3\u53c2\u6570\uff1a"+str(split)+str(fanganindex))
        return False,"","","",""




def maincalculate(split,initial0,initial1,finalt1,finalt2):
    fanganindex=1
    while(fanganindex<3):
        if fanganindex==1:
            index ,level =0 ,3
            time0 =time .time ()
            while (index <3):
                T1,pici1 ,t1 ,shunxu1,jieshuquanci1 =calculate (level,split,fanganindex,initial0,False,finalt1)
                index +=1
                if T1 ==True :
                    T11,pici11 ,t11 ,shunxu11,jieshuquanci11 =calculate (level,split,fanganindex,initial0,True,finalt1)
                    if T11==True:
                        T1,pici1 ,t1 ,shunxu1,jieshuquanci1=T11,pici11 ,t11 ,shunxu11,jieshuquanci11

                    print ("\u4f18\u5148\u7ea7\u522b\uff1a"+str (index ))
                    print (time .time ()-time0 )

                    break
                elif index ==1  :
                    level =4
                elif index ==2 :
                    level =5

        elif fanganindex ==2:

            index ,level =0 ,0
            time0 =time .time ()
            while (index <3):
                T2 ,pici2 ,t2 ,shunxu2 ,jieshuquanci2=calculate (level,split ,fanganindex,initial1,False,finalt2)
                index +=1
                if T2 ==True :

                    T21 ,pici21 ,t21 ,shunxu21 ,jieshuquanci21=calculate (level,split ,fanganindex,initial1,True,finalt2)
                    if T21==True:
                        T2 ,pici2 ,t2 ,shunxu2 ,jieshuquanci2=T21 ,pici21 ,t21 ,shunxu21 ,jieshuquanci21

                    print ("\u4f18\u5148\u7ea7\u522b\uff1a"+str (index ))
                    print (time .time ()-time0 )
                    break
                elif index ==1:
                    level =1
                elif index ==2  :
                    level =2

        fanganindex+=1
    return T1, pici1, t1,shunxu1,jieshuquanci1,T2 ,pici2 ,t2 ,shunxu2,jieshuquanci2

split=False
finalt1,finalt2=[[] for i in range(guonum)],[[] for i in range(guonum)]
T1, pici1, t1,shunxu1,jieshuquanci1,T2 ,pici2 ,t2 ,shunxu2,jieshuquanci2=maincalculate(split,stateinitial,stateinitial,finalt1,finalt2)
solution1_stage_frames=[]
solution2_stage_frames=[]


if (T1==False and T2==False):
    demand10=copy.deepcopy(demand1)


    demand20=copy.deepcopy(demand2)
    demand2=[0,0,0,0,0,0,0]
    yuliu=[0,3,3]
    T1, pici1, t1,shunxu1,jieshuquanci1,T2 ,pici2 ,t2 ,shunxu2,jieshuquanci2=maincalculate(split,stateinitial,stateinitial,finalt1,finalt2)
    split=True
    demand1=demand20

    Weightt=10000
    yuliu=[0,2,3]
    if len(t1)>0:
        for l in range(guonum):

            for i in range(len(t1.iloc[l]),0,-1):
                if t1.iloc[l,i-1]!='':
                    finalt1[l]=t1.iloc[l,i-1]
                    break
    else:
        finalt1=[0 for i in range(guonum)]
    if len(t2)>0:
        for l in range(guonum):
            for i in range(len(t2.iloc[l]),0,-1):
                if t2.iloc[l,i-1]!='':
                    finalt2[l]=t2.iloc[l,i-1]
                    break



    stage2_initial1=copy.deepcopy(jieshuquanci1)
    stage2_initial2=copy.deepcopy(jieshuquanci2)
    T11, pici11, t11,shunxu11,jieshuquanci11,T21 ,pici21 ,t21 ,shunxu21,jieshuquanci21=maincalculate(split,stage2_initial1,stage2_initial2,finalt1,finalt2)

    if T1==True and T11==True:
        solution1_stage_frames=[
            (copy.deepcopy(shunxu1), copy.deepcopy(pici1), copy.deepcopy(t1), copy.deepcopy(orig_stateinitial)),
            (copy.deepcopy(shunxu11), copy.deepcopy(pici11), copy.deepcopy(t11), stage2_initial1),
        ]
    if T2==True and T21==True:
        solution2_stage_frames=[
            (copy.deepcopy(shunxu2), copy.deepcopy(pici2), copy.deepcopy(t2), copy.deepcopy(orig_stateinitial)),
            (copy.deepcopy(shunxu21), copy.deepcopy(pici21), copy.deepcopy(t21), stage2_initial2),
        ]

    if T11==False or T1==False:
        print("\u65b9\u6848\u4e00\u65e0\u89e3")
    else:
        pici1=pici1.astype(object)
        shunxu1=shunxu1.astype(object)
        t1=t1.astype(object)
        df9= ["" for i in range(guonum)]
        for i in range(9):
            pici1["\u7b2c"+str(i+9)+"\u5708"]=df9
            shunxu1["\u7b2c"+str(i+9)+"\u5708"]=df9
            t1["\u7b2c"+str(i+9)+"\u5708"]=df9
        pici1=pici1.astype(object)
        shunxu1=shunxu1.astype(object)
        t1=t1.astype(object)

        for i in range(guonum):
            index=1
            tpre=0
            for j in range(1,len(pici1.iloc[i,:])):
                if pici1.iloc[i,j]=="" and pici11.iloc[i,index]!="":
                    pici1.iloc[i,j]=pici11.iloc[i,index]
                    t1.iloc[i,j]=t1.iloc[i,j-1]+t11.iloc[i,index]-tpre
                    shunxu1.iloc[i,j]=shunxu11.iloc[i,index]
                    tpre=t11.iloc[i,index]
                    index+=1
    if T2==False or T21==False:
        print("\u65b9\u6848\u4e8c\u65e0\u89e3")
    else:
        pici2=pici2.astype(object)
        shunxu2=shunxu2.astype(object)
        t2=t2.astype(object)
        df9= ["" for i in range(guonum)]
        for i in range(9):

            pici2["\u7b2c"+str(i+9)+"\u5708"]=df9
            shunxu2["\u7b2c"+str(i+9)+"\u5708"]=df9
            t2["\u7b2c"+str(i+9)+"\u5708"]=df9
        pici2=pici2.astype(object)
        shunxu2=shunxu2.astype(object)
        t2=t2.astype(object)
        for i in range(guonum):
            index=1
            tpre=0
            for j in range(1,len(pici2.iloc[i,:])):
                if pici2.iloc[i,j]=="" and pici21.iloc[i,index]!="":
                    pici2.iloc[i,j]=pici21.iloc[i,index]
                    t2.iloc[i,j]=t2.iloc[i,j-1]+t21.iloc[i,index]-tpre
                    shunxu2.iloc[i,j]=shunxu21.iloc[i,index]
                    tpre=t21.iloc[i,index]
                    index+=1

shunxu1.to_excel('\u5206\u6392\u7a0b\u7ed3\u679c\u751f\u4ea7\u987a\u5e8f1'+'.xlsx')
pici1.to_excel('\u5206\u6392\u7a0b\u7ed3\u679c\u6279\u6b211'+'.xlsx')
t1.to_excel('\u5206\u6392\u7a0b\u7ed3\u679c\u65f6\u95f41'+'.xlsx')
shunxu2.to_excel('\u5206\u6392\u7a0b\u7ed3\u679c\u751f\u4ea7\u987a\u5e8f2'+'.xlsx')
pici2.to_excel('\u5206\u6392\u7a0b\u7ed3\u679c\u6279\u6b212'+'.xlsx')
t2.to_excel('\u5206\u6392\u7a0b\u7ed3\u679c\u65f6\u95f42'+'.xlsx')

def dataframes_to_stage_json(shunxu_df, pici_df, t_df, state_initial):
    pots = []
    num_pots = len(state_initial)
    for l in range(num_pots):
        pot = {
            "pot_id": l + 1,
            "initial_round": int(state_initial[l]),
            "rounds": []
        }
        for col_idx in range(1, len(shunxu_df.columns)):
            prod = shunxu_df.iloc[l, col_idx]
            if prod == "" or (isinstance(prod, float) and np.isnan(prod)):
                continue
            batch_val = pici_df.iloc[l, col_idx]
            time_val = t_df.iloc[l, col_idx]

            round_entry = {
                "product": str(prod),
                "batch": int(batch_val) if batch_val != "" and not (isinstance(batch_val, float) and np.isnan(batch_val)) else 0,
                "cumulative_time": int(time_val) if time_val != "" and not (isinstance(time_val, float) and np.isnan(time_val)) else 0
            }
            pot["rounds"].append(round_entry)
        pots.append(pot)
    return {"pots": pots}


def stage_frames_to_solution_json(stage_frames):
    return {
        "stages": [
            dataframes_to_stage_json(shunxu_df, pici_df, t_df, state_initial)
            for shunxu_df, pici_df, t_df, state_initial in stage_frames
        ]
    }


def write_testdata_json(filepath, state_initial, d1, d2, yu):
    testdata = {
        "stateinitial": [int(x) for x in state_initial],
        "demand1": [int(x) for x in d1],
        "demand2": [int(x) for x in d2],
        "yuliu": [int(x) for x in yu]
    }
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(testdata, f, ensure_ascii=False, indent=4)
    print(f"\u5df2\u8f93\u51fa\u6d4b\u8bd5\u6570\u636e: {filepath}")


write_testdata_json('testdata.json', orig_stateinitial, orig_demand1, orig_demand2, orig_yuliu)

if isinstance(shunxu1, pd.DataFrame):
    frames1 = solution1_stage_frames or [
        (shunxu1, pici1, t1, orig_stateinitial)
    ]
    sol1 = stage_frames_to_solution_json(frames1)
    with open('solution1.json', 'w', encoding='utf-8') as f:
        json.dump(sol1, f, ensure_ascii=False, indent=4)
    print("\u5df2\u8f93\u51fa\u65b9\u6848\u4e00: solution1.json")
else:
    print("\u65b9\u6848\u4e00\u65e0\u6709\u6548\u89e3\uff0c\u8df3\u8fc7 solution1.json \u8f93\u51fa")

if isinstance(shunxu2, pd.DataFrame):
    frames2 = solution2_stage_frames or [
        (shunxu2, pici2, t2, orig_stateinitial)
    ]
    sol2 = stage_frames_to_solution_json(frames2)
    with open('solution2.json', 'w', encoding='utf-8') as f:
        json.dump(sol2, f, ensure_ascii=False, indent=4)
    print("\u5df2\u8f93\u51fa\u65b9\u6848\u4e8c: solution2.json")
else:
    print("\u65b9\u6848\u4e8c\u65e0\u6709\u6548\u89e3\uff0c\u8df3\u8fc7 solution2.json \u8f93\u51fa")

print("\nJSON \u6587\u4ef6\u53ef\u914d\u5408 verifier.py / objective.py \u4f7f\u7528:")
print("  python verifier.py --solution solution1.json --testdata testdata.json --level 3")
print("  python objective.py --solution solution1.json --testdata testdata.json --level 3")

