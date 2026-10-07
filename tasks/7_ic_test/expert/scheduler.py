







import pandas as pd
import numpy as np
import random
from numpy import nan
import time
import datetime
import random
import pytz
import math

from ortools.linear_solver import pywraplp
from datetime import timedelta,date
import copy





def scheduling0(day,result0,data411):


    dfdanzi=result0["\u4efb\u52a1\u5355\u53f7"].unique().tolist()
    data411["\u662f\u5426\u5220\u9664"]=0
    for i in range(len(data411)):
        if  data411["\u4efb\u52a1\u5355\u53f7"].iloc[i] in dfdanzi:
            result=result0[result0["\u4efb\u52a1\u5355\u53f7"]==data411["\u4efb\u52a1\u5355\u53f7"].iloc[i]]
            fenpeiall=sum(result["\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf"])
            if int(fenpeiall-result["\u8ba2\u5355\u603b\u91cf"].iloc[0])==0:
                data411.loc[i,"\u662f\u5426\u5220\u9664"]=1
            else:
                data411.loc[i,"\u8bd5\u9a8c\u6570\u91cf"]=int(data411.loc[i,"\u8bd5\u9a8c\u6570\u91cf"]-fenpeiall)
    data1=data411[data411["\u662f\u5426\u5220\u9664"]==0]
    data1=data1.drop(["\u662f\u5426\u5220\u9664"],axis=1)

    data0=data1
    data0.to_excel("remaining_orders.xlsx", sheet_name="4.12", index=False)
    return data0


def add_team(base_area):
    team = 0
    begin = 0
    end = random.randrange(2, 5)
    max_index = base_area.shape[0]
    while end < max_index + 4:
        team += 1
        for i in range(begin, end):
            base_area.loc[i, '\u533a\u4f4d\u7ec4'] = team
            if i == end - 1:
                begin = end
                end += random.randrange(2, 5)
        if team == 4:
            team = 0
    return base_area


def create_one_data(task, base_ability, base_board, base_equ, base_area, writer, sheet_name):
    row_num = 0
    for index, row in task.iterrows():
        specs = []
        set_types = set()
        marCode = row['\u7269\u6599\u7f16\u7801']
        df_spec = base_ability.query('\u7269\u6599\u7f16\u7801 == "%s"' % marCode.strip())
        if df_spec.empty:
            continue
        else:
            for index_spec, row_spec in df_spec.iterrows():
                if row_spec['\u8001\u70bc\u677f\u578b\u53f7'] is not nan:
                    specs = row_spec['\u8001\u70bc\u677f\u578b\u53f7'].split(',')
        if len(specs) == 0:
            continue
        else:
            for spec in specs:
                df_board = base_board.query('\u8001\u70bc\u677f\u578b\u53f7 == "%s"' % spec.strip())
                if df_board.empty:
                    print('\u8001\u70bc\u677f\u578b\u53f7' + '\u672a\u5728\u8001\u70bc\u677f\u8868\u627e\u5230\u5bf9\u5e94\u8001\u70bc\u677f\u578b\u53f7')
                else:
                    for index_board, row_board in df_board.iterrows():
                        set_types.add(row_board['\u8001\u70bc\u8bbe\u5907\u7c7b\u578b'])
        if len(set_types) == 0:
            print('\u4efb\u52a1\u5355\u53f7\u4e3a\u672a\u5728\u8001\u70bc\u677f\u8868\u627e\u5230\u5bf9\u5e94\u8001\u70bc\u677f\u578b\u53f7')
        else:
            for set_type in set_types:
                df_equ = base_equ.query('\u8001\u70bc\u8bbe\u5907\u7c7b\u578b == "%s"' % set_type.strip())
                if df_equ.empty:
                    print('\u672a\u5728\u8001\u70bc\u8bbe\u5907\u8868\u627e\u5230\u8001\u70bc\u8bbe\u5907\u7c7b\u578b\uff1a')
                else:
                    result = base_area[base_area['\u8bbe\u5907\u7f16\u7801'].isin(df_equ['\u8bbe\u5907\u7f16\u7801'])]
                    new_result = result.copy()
                    new_result.loc[:, '\u4efb\u52a1\u5355\u53f7'] = row['\u4efb\u52a1\u5355\u53f7']
                    if row_num == 0:
                        new_result.to_excel(excel_writer=writer, startrow=row_num, index=None, sheet_name=sheet_name)
                        row_num += new_result.shape[0] + 1
                    else:
                        new_result.to_excel(excel_writer=writer, startrow=row_num, index=None, header=None,
                                            sheet_name=sheet_name)
                        row_num += new_result.shape[0]
    return writer


def create_eight_data(task, base_ability, base_board, base_equ, base_area, writer, sheet_name):
    row_num = 0

    for index, row in task.iterrows():
        spec = row['\u7269\u6599\u7f16\u7801']
        df_spec = base_ability.query('\u7269\u6599\u7f16\u7801 == "%s"' % spec.strip())
        set_specs = set()
        if not df_spec.empty:
            for index_spec, row_spec in df_spec.iterrows():
                if row_spec['\u8001\u70bc\u677f\u578b\u53f7'] is not nan:
                    set_specs.add(row_spec['\u8001\u70bc\u677f\u578b\u53f7'])

        set_types = set()
        for set_spec in set_specs:
            df_board = base_board.query('\u8001\u70bc\u677f\u578b\u53f7 == "%s"' % set_spec.strip())
            if not df_board.empty:
                for index_board, row_board in df_board.iterrows():
                    set_types.add(row_board['\u8001\u70bc\u8bbe\u5907\u7c7b\u578b'])

        for set_type in set_types:
            df_equ = base_equ.query('\u8001\u70bc\u8bbe\u5907\u7c7b\u578b == "%s"' % set_type.strip())
            if not df_equ.empty:
                result = base_area[base_area['\u8bbe\u5907\u7f16\u7801'].isin(df_equ['\u8bbe\u5907\u7f16\u7801'])]
                new_result = result.copy()
                new_result.loc[:, '\u4efb\u52a1\u5355\u53f7'] = row['\u4efb\u52a1\u5355\u53f7']

                new_result['\u8bbe\u5907\u533a\u4f4d\u7f16\u53f7'] = ''
                new_result['\u8bbe\u5907\u7f16\u7801'] = new_result['\u8bbe\u5907\u7f16\u7801'].astype(str)
                new_result['\u4efb\u52a1\u5355\u53f7'] = new_result['\u4efb\u52a1\u5355\u53f7'].astype(str)
                if row_num == 0:
                    new_result.to_excel(excel_writer=writer, startrow=row_num, index=None, sheet_name=sheet_name)
                    row_num += new_result.shape[0] + 1
                else:
                    new_result.to_excel(excel_writer=writer, startrow=row_num, index=None, header=None, sheet_name=sheet_name)
                    row_num += new_result.shape[0]
    return writer
def daycal(day,task_all,base_ability,base_board,base_equ,base_area):


    writer = pd.ExcelWriter('matching.xlsx')
    task = task_all.copy()

    base_area = add_team(base_area)
    sheet_name = '\u6392\u7a0b\u8303\u56f4'
    writer = create_one_data(task, base_ability, base_board, base_equ, base_area, writer, sheet_name)

    writer.close()



def scheduling2(day,df,dset0,dset1,dset2,dset3,data1,target,t0,tend):
    s1=time.time()

    print("start building")
    data=copy.deepcopy(data1)
    xutask=data1.sort_values("\u8bd5\u9a8c\u6570\u91cf",ascending=True,inplace=False)
    zws=xutask["\u8bd5\u9a8c\u6570\u91cf"].iloc[(int(len(xutask)/3))]
    import re

    df.drop_duplicates(inplace=True)
    df.sort_values("\u4efb\u52a1\u5355\u53f7",ascending=True,inplace=True)
    dfdanzi=df['\u4efb\u52a1\u5355\u53f7'].drop_duplicates().tolist()
    dfshebei=df["\u8bbe\u5907\u7f16\u7801"].drop_duplicates().tolist()

    dfllbxh=[]

    dset0["\u7269\u6599\u7f16\u7801"]=dset0["\u7269\u6599\u7f16\u7801"].fillna(0)


    for i in range(len(dset1)):
        idx = dset1.index[i]
        station_count = dset1.at[idx, "\u53ef\u7528\u5de5\u4f4d\u6570"]
        if isinstance(station_count, str) and "+" in station_count:
            dset1.at[idx, "\u53ef\u7528\u5de5\u4f4d\u6570"] = station_count.split("+")[0]

    dset1["\u53ef\u7528\u5de5\u4f4d\u6570"] = pd.to_numeric(dset1["\u53ef\u7528\u5de5\u4f4d\u6570"], errors="coerce").fillna(0)
    dset1["\u8001\u70bc\u677f\u72b6\u6001"]=dset1["\u8001\u70bc\u677f\u72b6\u6001"].fillna('\u7a7a\u95f2')
    dset1.sort_values("\u53ef\u7528\u5de5\u4f4d\u6570",ascending=False,inplace=True)


    dset2["\u533a\u4f4d\u8d1f\u7535\u538b"]=nan
    for col in ["\u533a\u4f4d\u7535\u538b", "\u533a\u4f4d\u8d1f\u7535\u538b", "V_MAX", "\u533a\u4f4d\u7535\u6d41"]:
        dset2[col] = dset2[col].astype(object)
    for i in range(len(dset2)):
        idx = dset2.index[i]
        voltage_value = dset2.at[idx, "\u533a\u4f4d\u7535\u538b"]
        if not pd.isna(voltage_value):
            voltage_text = str(voltage_value)
            voltage_nums = re.findall(r"-?\d+\.?\d*e?-?\d*?", voltage_text)
            if '±' in voltage_text and voltage_nums:
                dset2.at[idx, "\u533a\u4f4d\u8d1f\u7535\u538b"] = float(voltage_nums[0])
            if '-' in voltage_text and voltage_nums:
                dset2.at[idx, "\u533a\u4f4d\u8d1f\u7535\u538b"] = float(voltage_nums[0])
                voltage_text = '0V'
                dset2.at[idx, "\u533a\u4f4d\u7535\u538b"] = voltage_text

            if ('kV' in voltage_text or 'KV' in voltage_text) and voltage_nums:
                dset2.at[idx, "\u533a\u4f4d\u7535\u538b"] = 1000*float(voltage_nums[0])
                if not pd.isna(dset2.at[idx, "\u533a\u4f4d\u8d1f\u7535\u538b"]):
                    dset2.at[idx, "\u533a\u4f4d\u8d1f\u7535\u538b"] = 1000*float(dset2.at[idx, "\u533a\u4f4d\u8d1f\u7535\u538b"])

            elif voltage_nums:
                dset2.at[idx, "\u533a\u4f4d\u7535\u538b"] = float(voltage_nums[0])
        elif dset2.at[idx, "\u533a\u4f4d\u72b6\u6001"]=='\u8bd5\u9a8c\u4e2d' :
            dset2.at[idx, "\u533a\u4f4d\u7535\u538b"] = 0
            dset2.at[idx, "\u533a\u4f4d\u8d1f\u7535\u538b"] = 0

        vmax_value = dset2.at[idx, "V_MAX"]
        if not pd.isna(vmax_value):
            vmax_nums = re.findall(r"-?\d+\.?\d*e?-?\d*?", str(vmax_value))
            dset2.at[idx, "V_MAX"] = float(vmax_nums[0]) if vmax_nums else 0
        else:
            dset2.at[idx, "V_MAX"] = 0


    for i in range(len(dset2)):
        idx = dset2.index[i]
        current_value = dset2.at[idx, "\u533a\u4f4d\u7535\u6d41"]
        if not pd.isna(current_value):
            current_text = str(current_value)
            current_nums = re.findall(r"-?\d+\.?\d*e?-?\d*?", current_text)
            if current_nums:
                if 'mA' in current_text:
                    dset2.at[idx, "\u533a\u4f4d\u7535\u6d41"] = float(current_nums[0])
                else:
                    dset2.at[idx, "\u533a\u4f4d\u7535\u6d41"] = 1000*float(current_nums[0])
        elif dset2.at[idx, "\u533a\u4f4d\u72b6\u6001"]=='\u8bd5\u9a8c\u4e2d' :
            dset2.at[idx, "\u533a\u4f4d\u7535\u6d41"] = 0

    dset2["\u533a\u4f4d\u7535\u538b"] = pd.to_numeric(dset2["\u533a\u4f4d\u7535\u538b"], errors="coerce")
    dset2["\u533a\u4f4d\u8d1f\u7535\u538b"] = pd.to_numeric(dset2["\u533a\u4f4d\u8d1f\u7535\u538b"], errors="coerce")
    dset2["V_MAX"] = pd.to_numeric(dset2["V_MAX"], errors="coerce").fillna(0)
    dset2["\u533a\u4f4d\u7535\u6d41"] = pd.to_numeric(dset2["\u533a\u4f4d\u7535\u6d41"], errors="coerce")


    dset3["\u8bbe\u5907\u6e29\u5ea6"] = dset3["\u8bbe\u5907\u6e29\u5ea6"].astype(object)
    for i in range(len(dset3)):
        idx = dset3.index[i]
        if not pd.isna(dset3.at[idx, "\u8bbe\u5907\u6e29\u5ea6"]):
            dset3.at[idx, "\u8bbe\u5907\u6e29\u5ea6"] = int(re.findall(r"\d+", str(dset3.at[idx, "\u8bbe\u5907\u6e29\u5ea6"]))[0])
    dset3["\u8bbe\u5907\u6e29\u5ea6"] = pd.to_numeric(dset3["\u8bbe\u5907\u6e29\u5ea6"], errors="coerce")






    data["\u6e29\u5ea6"]=data["\u6e29\u5ea6"].fillna('25c')
    data["\u7535\u538b"]=data["\u7535\u538b"].fillna('0v')
    data["\u7535\u6d41"]= data["\u7535\u6d41"].fillna('0mA')
    data["\u8d1f\u7535\u538b"]=0
    for col in ["\u65f6\u95f4", "\u6e29\u5ea6", "\u7535\u538b", "\u7535\u6d41", "\u8d1f\u7535\u538b"]:
        data[col] = data[col].astype(object)
    for i in range(len(data)):
        idx = data.index[i]
        data.at[idx, "\u65f6\u95f4"] = int(re.findall(r"\d+", str(data.at[idx, "\u65f6\u95f4"]))[0])
        data.at[idx, "\u6e29\u5ea6"] = int(re.findall(r"\d+", str(data.at[idx, "\u6e29\u5ea6"]))[0])
        voltage_value = data.at[idx, "\u7535\u538b"]
        voltage_text = str(voltage_value)
        voltage_nums = re.findall(r"-?\d+\.?\d*e?-?\d*?", voltage_text)
        if isinstance(voltage_value, str) and "±" in voltage_value and voltage_nums:
            data.at[idx, "\u8d1f\u7535\u538b"] = float(voltage_nums[0])
        if isinstance(voltage_value, str) and "-" in voltage_value and voltage_nums:
            data.at[idx, "\u8d1f\u7535\u538b"] = float(voltage_nums[0])
            voltage_text = '0v'
            data.at[idx, "\u7535\u538b"] = voltage_text
        if isinstance(voltage_value, str) and ("kV" in voltage_value
                                              or "KV" in voltage_value) and voltage_nums:
            data.at[idx, "\u7535\u538b"] = 1000*float(voltage_nums[0])
            data.at[idx, "\u8d1f\u7535\u538b"] = 1000*float(data.at[idx, "\u8d1f\u7535\u538b"])

        elif voltage_nums:
            data.at[idx, "\u7535\u538b"] = float(re.findall(r"-?\d+\.?\d*e?-?\d*?", voltage_text)[0])

        current_value = data.at[idx, "\u7535\u6d41"]
        current_text = str(current_value)
        current_nums = re.findall(r"-?\d+\.?\d*e?-?\d*?", current_text)
        if current_nums:
            if isinstance(current_value, str) and "mA" in current_value:
                data.at[idx, "\u7535\u6d41"] = float(current_nums[0])
            else:
                data.at[idx, "\u7535\u6d41"] = 1000*float(current_nums[0])
    data["\u65f6\u95f4"] = pd.to_numeric(data["\u65f6\u95f4"], errors="coerce")
    data["\u6e29\u5ea6"] = pd.to_numeric(data["\u6e29\u5ea6"], errors="coerce")
    data["\u7535\u538b"] = pd.to_numeric(data["\u7535\u538b"], errors="coerce")
    data["\u8d1f\u7535\u538b"] = pd.to_numeric(data["\u8d1f\u7535\u538b"], errors="coerce").fillna(0)
    data["\u7535\u6d41"] = pd.to_numeric(data["\u7535\u6d41"], errors="coerce")

    dfwendu1=data["\u6e29\u5ea6"].unique().tolist()
    dfwendu2=dset3["\u8bbe\u5907\u6e29\u5ea6"].unique().tolist()
    dfwendu=dfwendu1+dfwendu2
    dfwendu=list(set(dfwendu))
    dfwendu = [x for x in dfwendu if str(x) != 'nan']
    maxtime=max(data["\u65f6\u95f4"])

    single=[]
    msingle=[]
    bianmaset=dset3['\u8bbe\u5907\u7c7b\u578b\u7f16\u7801'].unique()
    for index in bianmaset:
        if len(dset3[dset3["\u8bbe\u5907\u7c7b\u578b\u7f16\u7801"]==index])==1:
            single.append(index)
            p=dset3[dset3["\u8bbe\u5907\u7c7b\u578b\u7f16\u7801"]==index]
    msingle=pd.DataFrame(msingle,columns=["\u8bbe\u5907\u7f16\u7801"])
    print("finish data presolving")
    import numpy as np
    solver = pywraplp.Solver('SolveIntegerProblem',pywraplp.Solver.CBC_MIXED_INTEGER_PROGRAMMING)

    objective = solver.Objective()

    cij={}

    xhij={}
    dij={}
    XjT={}
    Yijk={}
    njv123={}
    Cjv123={}



    Consnjv12={}

    Consmmax=[[] for i in range(len(dset3))]
    Consd=[[] for i in range(len(dfdanzi))]
    Cons2=[[] for i in range(len(dfshebei))]
    Cons3=[[] for i in range(len(dfshebei))]
    Cons5=[[] for i in range(len(dfdanzi))]
    Cons6=[[] for i in range(len(dfshebei))]
    Cons61=[[] for i in range(len(dfshebei))]


    Cons71=[[] for i in range(len(dfshebei))]
    Cons72=[[] for i in range(len(dfshebei))]
    Cons73=[[] for i in range(len(dfshebei))]
    Cons74=[[] for i in range(len(dfshebei))]
    Cons75=[[] for i in range(len(dfshebei))]
    Cons76=[[] for i in range(len(dfshebei))]
    Cons77=[[] for i in range(len(dfshebei))]
    Cons78=[[] for i in range(len(dfshebei))]

    jqwz1=[[] for i in range(len(dfshebei))]
    jqwz2=[[] for i in range(len(dfshebei))]
    jqwz3=[[] for i in range(len(dfshebei))]
    jqwz4=[[] for i in range(len(dfshebei))]

    jqwz5=[[] for i in range(len(dfshebei))]
    jqwz6=[[] for i in range(len(dfshebei))]
    jqwz7=[[] for i in range(len(dfshebei))]
    jqwz8=[[] for i in range(len(dfshebei))]

    dfdianya=[[] for i in range(len(dfshebei))]
    dfqwzdianya=[[] for i in range(len(dfshebei))]
    fllbxh= [[] for i in range(len(dfdanzi))]
    isbusy=[False for i in range(len(dfshebei))]
    for j in range(len(dfshebei)):
        dset2j=dset2[dset2["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j]]
        for k in range(len(dset2j)):
            if (pd.to_datetime(dset2j["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"].iloc[k], format="mixed")-t0).days>1:
                isbusy[j]=True
                break
    setllbij=[]




    for i in range(len(dfdanzi)):

        ordanzi=data[data["\u4efb\u52a1\u5355\u53f7"]==dfdanzi[i]]
        if len(ordanzi)==0:
            print("\u4efb\u52a1\u5355\u53f7\u67e5\u8be2\u4e0d\u5230"+str(dfdanzi[i]))

        guige=ordanzi["\u7269\u6599\u7f16\u7801"].iloc[0]

        set0i=dset0[dset0["\u7269\u6599\u7f16\u7801"]==guige]
        n=set0i["\u5668\u4ef6\u5360\u533a\u4f4d\u6570"].iloc[0]
        li=set0i["\u8001\u70bc\u677f\u578b\u53f7"].iloc[0]
        llbxh=[]
        xh=[]
        if type(li)==str and ',' in li:

            xh=(li.split(','))
        else:
            xh.append(str(li))
        for j in xh:
            if j!='1070' and j!='1051':
                llbxh.append(j)
        fllbxh[i]=llbxh

    for i in range(len(dfdanzi)):
        for k in range(len(fllbxh[i])):
            dfllbxh.append(fllbxh[i][k])


    dfllbxh=list(set(dfllbxh))

    Cons4=[[] for i in range(len(dfllbxh))]
    for k in range(len(dfllbxh)):
        llb=dset1[dset1["\u8001\u70bc\u677f\u578b\u53f7"]==dfllbxh[k]]
        llbnum=0
        for i in range(len(llb)):
            if llb["\u8001\u70bc\u677f\u72b6\u6001"].iloc[i]=='\u7a7a\u95f2':
                llbnum+=1
            else:
                dset2i=dset2[dset2["\u5bf9\u5e94\u8001\u70bc\u677f"]==llb["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[i]]
                if len(dset2i)==0:
                    print("error\uff1a\u8001\u70bc\u4e2d\u7684\u8001\u70bc\u677f"+str(llb["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[i])+"\u627e\u4e0d\u5230\u5bf9\u5e94\u533a\u4f4d")
                    continue
                if (pd.to_datetime(dset2i["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"].iloc[0], format="mixed")-t0).days==1:
                    llbnum+=1

        Cons4[k]=solver.Constraint(-solver.infinity(),llbnum)


    for i in range(len(dfdanzi)):

        ordanzi=data[data["\u4efb\u52a1\u5355\u53f7"]==dfdanzi[i]]
        guige=ordanzi["\u7269\u6599\u7f16\u7801"].iloc[0]
        set0i=dset0[dset0["\u7269\u6599\u7f16\u7801"]==guige]
        n=set0i["\u5668\u4ef6\u5360\u533a\u4f4d\u6570"].iloc[0]
        jiaoqi=(pd.to_datetime(ordanzi["\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4"].iloc[0], format="mixed")-t0).days
        shiyandays=int(ordanzi["\u65f6\u95f4"].iloc[0]/24)

        if target=='1':
            JJDi=max(jiaoqi-shiyandays-1,0)+1
            if ordanzi["\u7d27\u6025\u72b6\u6001"].iloc[0]>1:
                JJDi=JJDi/(ordanzi["\u7d27\u6025\u72b6\u6001"].iloc[0]*M*10)

            else:
                JJDi=JJDi/(ordanzi["\u7d27\u6025\u72b6\u6001"].iloc[0]*M)

                if jiaoqi<shiyandays:
                    JJDi=JJDi/(1)
                elif jiaoqi<shiyandays+3:
                    JJDi=JJDi/(0.5)
                elif jiaoqi<shiyandays+7:
                    JJDi=JJDi/(0.1)
                elif jiaoqi<=shiyandays+12:
                    JJDi=JJDi/(0.05)

        elif target=='2':
            JJDi=max(jiaoqi-shiyandays-1,0)+1
            if jiaoqi<shiyandays:
                JJDi=JJDi/(1*M)
            elif jiaoqi<shiyandays+3:
                JJDi=JJDi/(0.5*M)
            elif jiaoqi<shiyandays+7:
                JJDi=JJDi/(0.1*M)
            elif jiaoqi<=shiyandays+12:
                JJDi=JJDi/(0.05*M)



        elif target=='3':

            factor=min(int(ordanzi["\u8bd5\u9a8c\u6570\u91cf"].iloc[0]/zws),5)
            print(zws)

            JJDi=max(jiaoqi-shiyandays,0)+1
            if factor<1:
                JJDi=1/M
            elif factor<3:
                JJDi=1/(0.5*M)
            elif factor<5:
                JJDi=1/(0.1*M)




        danzi=df[df["\u4efb\u52a1\u5355\u53f7"]==dfdanzi[i]]
        si=danzi["\u8bbe\u5907\u7f16\u7801"].drop_duplicates().tolist()
        shuliang=int(ordanzi["\u8bd5\u9a8c\u6570\u91cf"].iloc[0])
        Consd[i]=solver.Constraint(-solver.infinity(),float(ordanzi["\u8bd5\u9a8c\u6570\u91cf"].iloc[0]))
        Co=[[] for i in range(len(si))]
        Cons5[i]=Co

        for j in range(len(si)):

            Cons5[i][j]=solver.Constraint(-solver.infinity(),0)
            qwij=danzi[(danzi["\u8bbe\u5907\u7f16\u7801"]==si[j])]

            llbnum=0

            llbij=pd.DataFrame(columns=dset1.columns.values)
            for l in range(len(fllbxh[i])):
                tup1=(dfdanzi[i],si[j],fllbxh[i][l])
                llbij1=dset1[dset1["\u8001\u70bc\u677f\u578b\u53f7"]==fllbxh[i][l]]

                xh_lx=dset1[dset1["\u8001\u70bc\u677f\u578b\u53f7"]==fllbxh[i][l]]["\u8001\u70bc\u8bbe\u5907\u7c7b\u578b"].unique().tolist()
                sblx=dset3[dset3["\u8bbe\u5907\u7f16\u7801"]==si[j]]["\u8001\u70bc\u8bbe\u5907\u7c7b\u578b"].iloc[0]
                if sblx in xh_lx:
                    Yijk[tup1]=solver.IntVar(0,len(llbij1), str(i)+"o"+str(j)+"m"+str(l))
                else:
                    Yijk[tup1]=solver.IntVar(0,0, str(i)+"o"+str(j)+"m"+str(l))

                for k in range(len(dfllbxh)):
                    if dfllbxh[k]==fllbxh[i][l]:
                        Cons4[k].SetCoefficient(Yijk[tup1],1)

                if len(llbij1)==0:
                    continue
                mki=max(llbij1["\u53ef\u7528\u5de5\u4f4d\u6570"])
                hs=1

                if (llbij1["\u4e32\u884c\u884c\u4f4d\u6570"].iloc[0]==3):
                    if ordanzi["\u7535\u538b"].iloc[0]<=19:
                        hs=1
                    elif ordanzi["\u7535\u538b"].iloc[0]>19 and ordanzi["\u7535\u538b"].iloc[0]<=29:
                        hs=2
                    elif ordanzi["\u7535\u538b"].iloc[0]>29 :
                        hs=3
                    else:
                        print("error:\u5355\u53f7"+str(dfdanzi[[i]])+"\u5bf9\u5e94\u4e32\u884c\u8001\u70bc\u677f"+str(fllbxh[i][l]))

                Cons5[i][j].SetCoefficient(Yijk[tup1],-float(
                    mki*llbij1["\u5de5\u4f4d\u6700\u5927\u652f\u6570"].iloc[0]/hs))

                alllx=llbij1["\u8001\u70bc\u8bbe\u5907\u7c7b\u578b"].unique()

                for lx in alllx:
                    p=dset3[(dset3["\u8bbe\u5907\u7f16\u7801"]==si[j])&(dset3["\u8001\u70bc\u8bbe\u5907\u7c7b\u578b"]==lx)]
                    if len(p)>0:
                        llbij = pd.concat([llbij, llbij1])

            ls=(llbij["\u8001\u70bc\u677f\u578b\u53f7"].unique()).tolist()


            llbij.sort_values("\u53ef\u7528\u5de5\u4f4d\u6570",ascending=False,inplace=True)
            if(len(llbij)==0):

                break

            setllbij.append([dfdanzi[i],si[j],llbij["\u8001\u70bc\u677f\u578b\u53f7"].iloc[0],llbij["\u53ef\u7528\u5de5\u4f4d\u6570"].iloc[0]])
            llbnum=len(llbij)
            totalgw=0
            tup=(dfdanzi[i],si[j])

            if llbnum>=len(qwij)/n:
                totalgw+=sum(llbij["\u53ef\u7528\u5de5\u4f4d\u6570"][0:int(len(qwij)/n)])
                xhij[tup]=llbij["\u8001\u70bc\u677f\u578b\u53f7"][0:int(len(qwij)/n)].unique().tolist()
            else:
                totalgw=sum(llbij["\u53ef\u7528\u5de5\u4f4d\u6570"])
                xhij[tup]=llbij["\u8001\u70bc\u677f\u578b\u53f7"].unique().tolist()


            cij[tup]=totalgw*set0i["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u652f\u6570"].iloc[0]/set0i["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u6570"].iloc[0]


            if(cij[tup]==0):
                print("alert!!!!!!!!!!!!!cij=0")
            dij[tup]=solver.NumVar(0,float(ordanzi["\u8bd5\u9a8c\u6570\u91cf"].iloc[0]) , str(i)+"or"+str(j)+"ma")
            Consd[i].SetCoefficient(dij[tup],1)
            coefdij=float( set0i["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u6570"].iloc[0]/set0i["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u652f\u6570"].iloc[0])
            Cons5[i][j].SetCoefficient(dij[tup],coefdij)

            shu=int(shuliang/cij[tup])+1

            if shu >1 and shu/JJDi<=M and shu*shiyandays>=jiaoqi:
                shu=shu*M
            objective.SetCoefficient(dij[tup],shiyandays*shu/(JJDi))



    for j in range(len(dfshebei)):
        Cons2[j]=solver.Constraint(-solver.infinity(),1)
        tt=[[] for k in range(len(dfwendu))]
        Cons3[j]=tt
        shebei=df[df["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j]]
        sj=shebei["\u4efb\u52a1\u5355\u53f7"].drop_duplicates().tolist()


        dset3j=dset3[dset3["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j]]
        for k in range(len(dfwendu)):
            tup=(dfshebei[j],dfwendu[k])
            if dset3j["\u8bbe\u5907\u6e29\u5ea6"].iloc[0]==dfwendu[k]  and isbusy[j]:
                XjT[tup]=solver.IntVar(1,1, str(j)+"sb"+str(k)+"wd")
            else:
                XjT[tup]=solver.IntVar(0,1, str(j)+"sb"+str(k)+"wd")
            Cons2[j].SetCoefficient(XjT[tup],1)
            Cons3[j][k]=solver.Constraint(-solver.infinity(),0)
            Cons3[j][k].SetCoefficient(XjT[tup],-M)
            for i in range(len(sj)):
                ordanzi=data[data["\u4efb\u52a1\u5355\u53f7"]==sj[i]]

                wendu=ordanzi["\u6e29\u5ea6"].iloc[0]
                if wendu==dfwendu[k]:
                    tup0=(sj[i],dfshebei[j])
                    Cons3[j][k].SetCoefficient(dij[tup0],1)

        dianyaj=[]

        dset2v=(dset2[dset2["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j]])

        ddd=dset2v[dset2v["\u533a\u4f4d\u72b6\u6001"]=='\u8bd5\u9a8c\u4e2d']

        for i in range(len(dset2v)):
            if (not pd.isna(dset2v["\u533a\u4f4d\u7535\u538b"].iloc[i]) or not pd.isna(dset2v["\u533a\u4f4d\u7535\u6d41"].iloc[i] )
            or not pd.isna(dset2v["\u533a\u4f4d\u8d1f\u7535\u538b"].iloc[i] ) or len(ddd)>0):
                elem=dset2v["\u533a\u4f4d\u7535\u538b"].iloc[i]
                elema=dset2v["\u533a\u4f4d\u7535\u6d41"].iloc[i]
                elemb=dset2v["\u533a\u4f4d\u8d1f\u7535\u538b"].iloc[i]
                if np.isnan(elem):
                    elem=0
                if np.isnan(elema):
                    elema=0
                if np.isnan(elemb):
                    elemb=0
                dianyaj.append([elem,elema,elemb])
        for i in range(len(sj)):
            ordanzi=data[data["\u4efb\u52a1\u5355\u53f7"]==sj[i]]
            dianyaj.append([ordanzi["\u7535\u538b"].iloc[0],ordanzi["\u7535\u6d41"].iloc[0],ordanzi["\u8d1f\u7535\u538b"].iloc[0]])
        dianyaj = list(set([tuple(t) for t in dianyaj]))
        dianyaj = [list(v) for v in dianyaj]

        dianyaj.sort()



        dfdianya[j]=dianyaj
        thedd=dianyaj
        Cons6[j]=[[] for i in range(len(dianyaj))]
        Cons61[j]=[[] for i in range(len(dianyaj))]



        sbquwei=dset2[dset2["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j]]

        quweizu=sbquwei["\u533a\u4f4d\u7ec4"].unique().tolist()

        Nj1,Nj2,Nj3,Nj4=0,0,0,0
        Nj5,Nj6,Nj7,Nj8=0,0,0,0

        nv023={}
        for v in range(len(dfdianya[j])):
            nv023[(tuple(dfdianya[j][v]),2)]=0
            nv023[(tuple(dfdianya[j][v]),3)]=0
            nv023[(tuple(dfdianya[j][v]),4)]=0
            nv023[(tuple(dfdianya[j][v]),5)]=0
            nv023[(tuple(dfdianya[j][v]),6)]=0
            nv023[(tuple(dfdianya[j][v]),7)]=0
            nv023[(tuple(dfdianya[j][v]),8)]=0

            Cjv123[(dfshebei[j],thedd[v][0],1)]=0
            Cjv123[(dfshebei[j],thedd[v][0],2)]=0
            Cjv123[(dfshebei[j],thedd[v][0],3)]=0
            Cjv123[(dfshebei[j],thedd[v][0],4)]=0
            Cjv123[(dfshebei[j],thedd[v][0],5)]=0
            Cjv123[(dfshebei[j],thedd[v][0],6)]=0
            Cjv123[(dfshebei[j],thedd[v][0],7)]=0
            Cjv123[(dfshebei[j],thedd[v][0],8)]=0
        for i in quweizu:
            quweizui=sbquwei[(sbquwei["\u533a\u4f4d\u7ec4"]==i)]

            quweizunov=quweizui[(pd.isna(quweizui["\u533a\u4f4d\u7535\u538b"]) & pd.isna(quweizui["\u533a\u4f4d\u7535\u6d41"])
                                &pd.isna(quweizui["\u533a\u4f4d\u8d1f\u7535\u538b"]))]
            quweizuv=quweizui[(~pd.isna(quweizui["\u533a\u4f4d\u7535\u538b"]) | pd.isna(quweizui["\u533a\u4f4d\u7535\u6d41"])
                              |~pd.isna(quweizui["\u533a\u4f4d\u8d1f\u7535\u538b"]))]
            quweizuv["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"]=pd.to_datetime(quweizuv["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"], format="mixed")
            kongxianqw=quweizuv[quweizuv["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"]<=tend]
            busyqw=quweizuv[quweizuv["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"]>tend]

            if len(quweizui)-len(busyqw)>0 and len(busyqw)>0:
                elem=busyqw["\u533a\u4f4d\u7535\u538b"].iloc[0]
                if np.isnan(elem):
                    elem=0
                elema=busyqw["\u533a\u4f4d\u7535\u6d41"].iloc[0]
                if np.isnan(elema):
                    elema=0
                elemb=busyqw["\u533a\u4f4d\u8d1f\u7535\u538b"].iloc[0]
                if np.isnan(elemb):
                    elemb=0
                for v in range(len(dfdianya[j])):
                    if ((elem==dfdianya[j][v][0]) and (elema==dfdianya[j][v][1]) and
                     (elemb==dfdianya[j][v][2])) :
                        v0=tuple(dfdianya[j][v])
                        break



            if  len(quweizunov)+len(kongxianqw)==3:
                Nj3+=1
                jqwz3[j].append(i)
                for v in range(len(thedd)):
                    themaxv= sbquwei[sbquwei["\u533a\u4f4d\u7ec4"]==i]["V_MAX"].iloc[0]
                    if themaxv<thedd[v][0]:

                        Cjv123[(dfshebei[j],thedd[v][0],3)]+=1
            elif len(quweizunov)+len(kongxianqw)==2 :
                Nj2+=1
                jqwz2[j].append(i)
                for v in range(len(thedd)):
                    themaxv= sbquwei[sbquwei["\u533a\u4f4d\u7ec4"]==i]["V_MAX"].iloc[0]
                    if themaxv<thedd[v][0]:

                        Cjv123[(dfshebei[j],thedd[v][0],2)]+=1

            elif len(quweizunov)+len(kongxianqw)==1:
                Nj1+=1
                jqwz1[j].append(i)
                for v in range(len(thedd)):
                    themaxv= sbquwei[sbquwei["\u533a\u4f4d\u7ec4"]==i]["V_MAX"].iloc[0]
                    if themaxv<thedd[v][0]:

                        Cjv123[(dfshebei[j],thedd[v][0],1)]+=1

            elif len(quweizunov)+len(kongxianqw)==4:
                Nj4+=1
                jqwz4[j].append(i)
                for v in range(len(thedd)):
                    themaxv= sbquwei[sbquwei["\u533a\u4f4d\u7ec4"]==i]["V_MAX"].iloc[0]
                    if themaxv<thedd[v][0]:

                        Cjv123[(dfshebei[j],thedd[v][0],4)]+=1
            elif len(quweizunov)+len(kongxianqw)==5:
                Nj5+=1
                jqwz5[j].append(i)
                for v in range(len(thedd)):
                    themaxv= sbquwei[sbquwei["\u533a\u4f4d\u7ec4"]==i]["V_MAX"].iloc[0]
                    if themaxv<thedd[v][0]:

                        Cjv123[(dfshebei[j],thedd[v][0],5)]+=1
            elif len(quweizunov)+len(kongxianqw)==6:
                Nj6+=1
                jqwz6[j].append(i)
                for v in range(len(thedd)):
                    themaxv= sbquwei[sbquwei["\u533a\u4f4d\u7ec4"]==i]["V_MAX"].iloc[0]
                    if themaxv<thedd[v][0]:

                        Cjv123[(dfshebei[j],thedd[v][0],6)]+=1
            elif len(quweizunov)+len(kongxianqw)==7:
                Nj7+=1
                jqwz7[j].append(i)
                for v in range(len(thedd)):
                    themaxv= sbquwei[sbquwei["\u533a\u4f4d\u7ec4"]==i]["V_MAX"].iloc[0]
                    if themaxv<thedd[v][0]:

                        Cjv123[(dfshebei[j],thedd[v][0],7)]+=1
            elif len(quweizunov)+len(kongxianqw)==8:
                Nj8+=1
                jqwz8[j].append(i)
                for v in range(len(thedd)):
                    themaxv= sbquwei[sbquwei["\u533a\u4f4d\u7ec4"]==i]["V_MAX"].iloc[0]
                    if themaxv<thedd[v][0]:

                        Cjv123[(dfshebei[j],thedd[v][0],8)]+=1


            if len(quweizui)-len(busyqw)==1 and len(busyqw)>0:
                nv023[(v0,2)]+=1
            elif len(quweizui)-len(busyqw)==2 and len(busyqw)>0:
                nv023[(v0,3)]+=1
            elif len(quweizui)-len(busyqw)==3 and len(busyqw)>0:
                nv023[(v0,4)]+=1
            elif len(quweizui)-len(busyqw)==4 and len(busyqw)>0:
                nv023[(v0,5)]+=1
            elif len(quweizui)-len(busyqw)==5 and len(busyqw)>0:
                nv023[(v0,6)]+=1
            elif len(quweizui)-len(busyqw)==6 and len(busyqw)>0:
                nv023[(v0,7)]+=1
            elif len(quweizui)-len(busyqw)==7 and len(busyqw)>0:
                nv023[(v0,8)]+=1

            if len(busyqw)>0 and len(quweizui)-len(busyqw)>0 :
                dfqwzdianya[j].append([i,v0])





        for v in range(len(thedd)):
            intup=tuple(thedd[v])
            Cons6[j][v]=solver.Constraint(-solver.infinity(),0)
            Cons61[j][v]=solver.Constraint(-solver.infinity(),0)
            if Nj1>=0:
                tup2=(dfshebei[j],intup,1)
                njv123[tup2]=solver.IntVar(0,(Nj1-Cjv123[(dfshebei[j],thedd[v][0],1)]), str(j)+"sb"+str(v)+"dy"+str(1))
                Cons6[j][v].SetCoefficient(njv123[tup2],-1)

            if Nj2>=0:
                tup2=(dfshebei[j],intup,2)
                njv123[tup2]=solver.IntVar(0,(Nj2-Cjv123[(dfshebei[j],thedd[v][0],2)]), str(j)+"sb"+str(v)+"dy"+str(2))
                Cons6[j][v].SetCoefficient(njv123[tup2],-2)
                Cons61[j][v].SetCoefficient(njv123[tup2],-1)
            if Nj3>=0:
                tup2=(dfshebei[j],intup,3)
                njv123[tup2]=solver.IntVar(0,(Nj3-Cjv123[(dfshebei[j],thedd[v][0],3)]), str(j)+"sb"+str(v)+"dy"+str(3))
                Cons6[j][v].SetCoefficient(njv123[tup2],-3)
                Cons61[j][v].SetCoefficient(njv123[tup2],-1)

            if Nj4>=0:
                tup2=(dfshebei[j],intup,4)
                njv123[tup2]=solver.IntVar(0,(Nj4-Cjv123[(dfshebei[j],thedd[v][0],4)]), str(j)+"sb"+str(v)+"dy"+str(4))
                Cons6[j][v].SetCoefficient(njv123[tup2],-4)
                Cons61[j][v].SetCoefficient(njv123[tup2],-2)

            if Nj5>=0:
                tup2=(dfshebei[j],intup,5)
                njv123[tup2]=solver.IntVar(0,(Nj5-Cjv123[(dfshebei[j],thedd[v][0],5)]), str(j)+"sb"+str(v)+"dy"+str(5))
                Cons6[j][v].SetCoefficient(njv123[tup2],-5)
                Cons61[j][v].SetCoefficient(njv123[tup2],-2)

            if Nj6>=0:
                tup2=(dfshebei[j],intup,6)
                njv123[tup2]=solver.IntVar(0,(Nj6-Cjv123[(dfshebei[j],thedd[v][0],6)]), str(j)+"sb"+str(v)+"dy"+str(6))
                Cons6[j][v].SetCoefficient(njv123[tup2],-6)
                Cons61[j][v].SetCoefficient(njv123[tup2],-3)

            if Nj7>=0:
                tup2=(dfshebei[j],intup,7)
                njv123[tup2]=solver.IntVar(0,(Nj7-Cjv123[(dfshebei[j],thedd[v][0],7)]), str(j)+"sb"+str(v)+"dy"+str(7))
                Cons6[j][v].SetCoefficient(njv123[tup2],-7)
                Cons61[j][v].SetCoefficient(njv123[tup2],-3)

            if Nj8>=0:
                tup2=(dfshebei[j],intup,8)
                njv123[tup2]=solver.IntVar(0,(Nj8-Cjv123[(dfshebei[j],thedd[v][0],8)]), str(j)+"sb"+str(v)+"dy"+str(8))
                Cons6[j][v].SetCoefficient(njv123[tup2],-8)
                Cons61[j][v].SetCoefficient(njv123[tup2],-4)

            for i in range(len(sj)):
                ordanzi=data[data["\u4efb\u52a1\u5355\u53f7"]==sj[i]]

                if( (intup[0]==ordanzi["\u7535\u538b"].iloc[0])and(intup[1]==ordanzi["\u7535\u6d41"].iloc[0])
                and (intup[2]==ordanzi["\u8d1f\u7535\u538b"].iloc[0])):
                    for key in Yijk:
                        if key[0]==sj[i] and key[1]==dfshebei[j]:
                            hang0=dset0[dset0["\u7269\u6599\u7f16\u7801"]==ordanzi["\u7269\u6599\u7f16\u7801"].iloc[0]]

                            Cons6[j][v].SetCoefficient(Yijk[key],float(hang0["\u5668\u4ef6\u5360\u533a\u4f4d\u6570"].iloc[0]))
                            if hang0["\u5668\u4ef6\u5360\u533a\u4f4d\u6570"].iloc[0]>1:
                                Cons61[j][v].SetCoefficient(Yijk[key],1)

        if Nj1>0:
            Cons71[j]=solver.Constraint(-solver.infinity(),Nj1)
            for key in njv123:
                if key[0]==dfshebei[j] and key[2]==1:
                    Cons71[j].SetCoefficient(njv123[key],1)

        if Nj2>0:
            Cons72[j]=solver.Constraint(-solver.infinity(),Nj2)
            for key in njv123:
                if key[0]==dfshebei[j] and key[2]==2:
                    Cons72[j].SetCoefficient(njv123[key],1)

        if Nj3>0:
            Cons73[j]=solver.Constraint(-solver.infinity(),Nj3)
            for key in njv123:
                if key[0]==dfshebei[j] and key[2]==3:
                    Cons73[j].SetCoefficient(njv123[key],1)

        if Nj4>0:
            Cons74[j]=solver.Constraint(-solver.infinity(),Nj4)
            for key in njv123:
                if key[0]==dfshebei[j] and key[2]==4:
                    Cons74[j].SetCoefficient(njv123[key],1)

        if Nj5>0:
            Cons75[j]=solver.Constraint(-solver.infinity(),Nj5)
            for key in njv123:
                if key[0]==dfshebei[j] and key[2]==5:
                    Cons75[j].SetCoefficient(njv123[key],1)

        if Nj6>0:
            Cons76[j]=solver.Constraint(-solver.infinity(),Nj6)
            for key in njv123:
                if key[0]==dfshebei[j] and key[2]==6:
                    Cons76[j].SetCoefficient(njv123[key],1)

        if Nj7>0:
            Cons77[j]=solver.Constraint(-solver.infinity(),Nj7)
            for key in njv123:
                if key[0]==dfshebei[j] and key[2]==7:
                    Cons77[j].SetCoefficient(njv123[key],1)

        if Nj8>0:
            Cons78[j]=solver.Constraint(-solver.infinity(),Nj8)
            for key in njv123:
                if key[0]==dfshebei[j] and key[2]==8:
                    Cons78[j].SetCoefficient(njv123[key],1)



        for key in nv023:
            if key[1]==2 and nv023[key]>0:
                Consnjv12[(dfshebei[j],key[0],1)]=solver.Constraint(nv023[key],solver.infinity())
                Consnjv12[(dfshebei[j],key[0],1)].SetCoefficient(njv123[(dfshebei[j],key[0],1)],1)

            if key[1]==3 and nv023[key]>0:
                Consnjv12[(dfshebei[j],key[0],2)]=solver.Constraint(nv023[key],solver.infinity())
                Consnjv12[(dfshebei[j],key[0],2)].SetCoefficient(njv123[(dfshebei[j],key[0],2)],1)


            if key[1]==4 and nv023[key]>0:
                Consnjv12[(dfshebei[j],key[0],3)]=solver.Constraint(nv023[key],solver.infinity())
                Consnjv12[(dfshebei[j],key[0],3)].SetCoefficient(njv123[(dfshebei[j],key[0],3)],1)

            if key[1]==5 and nv023[key]>0:
                Consnjv12[(dfshebei[j],key[0],4)]=solver.Constraint(nv023[key],solver.infinity())
                Consnjv12[(dfshebei[j],key[0],4)].SetCoefficient(njv123[(dfshebei[j],key[0],4)],1)

            if key[1]==6 and nv023[key]>0:
                Consnjv12[(dfshebei[j],key[0],5)]=solver.Constraint(nv023[key],solver.infinity())
                Consnjv12[(dfshebei[j],key[0],5)].SetCoefficient(njv123[(dfshebei[j],key[0],5)],1)


            if key[1]==7 and nv023[key]>0:
                Consnjv12[(dfshebei[j],key[0],6)]=solver.Constraint(nv023[key],solver.infinity())
                Consnjv12[(dfshebei[j],key[0],6)].SetCoefficient(njv123[(dfshebei[j],key[0],6)],1)

            if key[1]==8 and nv023[key]>0:
                Consnjv12[(dfshebei[j],key[0],7)]=solver.Constraint(nv023[key],solver.infinity())
                Consnjv12[(dfshebei[j],key[0],7)].SetCoefficient(njv123[(dfshebei[j],key[0],7)],1)


    fushebei=dset3[~pd.isna(dset3["\u6240\u5c5e\u8bbe\u5907"])]["\u6240\u5c5e\u8bbe\u5907"].unique().tolist()
    Consamet={}
    for j in fushebei:
        dset3k=dset3[dset3["\u6240\u5c5e\u8bbe\u5907"]==j]
        if len(dset3k)>1:
            if dset3k["\u8bbe\u5907\u7f16\u7801"].iloc[0] in dfshebei and  dset3k["\u8bbe\u5907\u7f16\u7801"].iloc[1] in dfshebei :
                for k in range(len(dfwendu)):
                    tup=(j,dfwendu[k])
                    Consamet[(j,k)]=solver.Constraint(0,0)
                    Consamet[(j,k)].SetCoefficient(XjT[(dset3k["\u8bbe\u5907\u7f16\u7801"].iloc[0],dfwendu[k])],1)
                    Consamet[(j,k)].SetCoefficient(XjT[(dset3k["\u8bbe\u5907\u7f16\u7801"].iloc[1],dfwendu[k])],-1)


    objective.SetMaximization()
    s2=time.time()
    print('Time required to build model=', s2-s1)
    result_status = solver.Solve()

    assert result_status == pywraplp.Solver.OPTIMAL



    print('Number of variables =', solver.NumVariables())
    print('Number of constraints =', solver.NumConstraints())

    re=solver.Objective().Value()


    print('Solution:')



    print('Optimal objective value = %d' % re)

    muban=pd.read_excel("result_template.xlsx")
    result=pd.DataFrame(columns=muban.columns.values)
    index=0
    for key in dij:
        if dij[key].solution_value()>0:
            for key0 in Yijk:
                if key0[0]==key[0] and key0[1]==key[1] and Yijk[key0].solution_value()>0:
                    ordanzi=data[data["\u4efb\u52a1\u5355\u53f7"]==key[0]]
                    danzong=ordanzi["\u8bd5\u9a8c\u6570\u91cf"].iloc[0]
                    shijian=ordanzi["\u65f6\u95f4"].iloc[0]
                    wendu=ordanzi["\u6e29\u5ea6"].iloc[0]
                    dianya=ordanzi["\u7535\u538b"].iloc[0]
                    dianliu=ordanzi["\u7535\u6d41"].iloc[0]
                    jinjidu=ordanzi["\u7d27\u6025\u72b6\u6001"].iloc[0]
                    shengyut=(pd.to_datetime(ordanzi["\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4"].iloc[0], format="mixed")-t0).days-int(shijian/24)
                    if shengyut>=0:
                        chaoqi=0
                    else:
                        chaoqi=1

                    ditianshu=1
                    llbxh=key0[2]


                    for i in range(int(Yijk[key0].solution_value())):
                        if dij[key].solution_value()-int(dij[key].solution_value())<0.5:
                            dddd=int(dij[key].solution_value())
                        else:
                            dddd=int(dij[key].solution_value())+1
                        result.loc[index]=[index,key0[0],key0[1],dddd,
                                           danzong,shijian,wendu,dianya,ordanzi["\u8d1f\u7535\u538b"].iloc[0],
                                           dianliu,jinjidu,shengyut,ditianshu,llbxh,
                                           0,0,0,0,0,0,0,chaoqi,0]
                        index+=1

    result.set_index(["\u7d22\u5f15"], inplace=True)
    for col in ["\u8001\u70bc\u677f\u7f16\u53f7", "\u533a\u4f4d"]:
        result[col] = result[col].astype(object)
    allxh=result["\u8001\u70bc\u677f\u578b\u53f7"].unique().tolist()
    allxh.sort()

    indexxh=[0 for i in range(len(allxh))]
    llbyiyong=[]


    for i in range(len(result)):
        set1i=dset1[(dset1["\u8001\u70bc\u677f\u578b\u53f7"]==result.loc[i,"\u8001\u70bc\u677f\u578b\u53f7"])]

        for j in range(len(allxh)):
            if allxh[j]==result.loc[i,"\u8001\u70bc\u677f\u578b\u53f7"]:
                for k in range(len(set1i)):

                    if set1i["\u8001\u70bc\u677f\u72b6\u6001"].iloc[k]=='\u7a7a\u95f2'  and set1i["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[k] not in llbyiyong :

                        index=indexxh[j]
                        llbyiyong.append(set1i["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[k])
                        result.loc[i,"\u8001\u70bc\u677f\u7f16\u53f7"]=set1i["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[k]
                        result.loc[i,"\u8001\u70bc\u677f\u603b\u5de5\u4f4d\u6570"]=set1i["\u53ef\u7528\u5de5\u4f4d\u6570"].iloc[k]

                        indexxh[j]+=1
                        break
                    elif set1i["\u8001\u70bc\u677f\u72b6\u6001"].iloc[k]!='\u7a7a\u95f2':
                        dset2i=dset2[dset2["\u5bf9\u5e94\u8001\u70bc\u677f"]==set1i["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[k]]
                        if(pd.to_datetime(dset2i["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"].iloc[0], format="mixed")-t0).days==1 and set1i["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[k] not in llbyiyong:
                            index=indexxh[j]
                            llbyiyong.append(set1i["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[k])
                            result.loc[i,"\u8001\u70bc\u677f\u7f16\u53f7"]=set1i["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[k]
                            result.loc[i,"\u8001\u70bc\u677f\u603b\u5de5\u4f4d\u6570"]=set1i["\u53ef\u7528\u5de5\u4f4d\u6570"].iloc[k]

                            indexxh[j]+=1
                            break
    for j in range(len(dfshebei)):
        dset3i=dset3[dset3["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j]]
        if not pd.isna(dset3i["\u8bbe\u5907\u6e29\u5ea6"].iloc[0]):
            for k in range(len(dfwendu)):
                T=XjT[(dset3i["\u8bbe\u5907\u7f16\u7801"].iloc[0],dfwendu[k])].solution_value()
                if T>0:
                    print ("\u8bbe\u5907"+str(dfshebei[j])+"\u6e29\u5ea6"+str(dfwendu[k]))

    result_danzi=result["\u4efb\u52a1\u5355\u53f7"].unique().tolist()
    for i in range(len(result_danzi)):

        danzii=result[result["\u4efb\u52a1\u5355\u53f7"]==result_danzi[i]]
        si=danzii["\u8bbe\u5907\u7f16\u7801"].unique().tolist()
        for j in range(len(si)):
            sij=danzii[danzii["\u8bbe\u5907\u7f16\u7801"]==si[j]]
            sij.sort_values("\u8001\u70bc\u677f\u603b\u5de5\u4f4d\u6570",ascending=False,inplace=True)
            tofenpei=sij["\u5206\u914d\u8ba2\u5355\u6570\u91cf"].iloc[0]
            for l in range(len(sij)):
                dset1i=dset1[dset1["\u8001\u70bc\u677f\u7f16\u53f7"]==sij["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[l]]
                ordanzi=data[data["\u4efb\u52a1\u5355\u53f7"]==sij["\u4efb\u52a1\u5355\u53f7"].iloc[l]]
                wuliao=ordanzi["\u7269\u6599\u7f16\u7801"].iloc[0]
                dset0i=dset0[dset0["\u7269\u6599\u7f16\u7801"]==wuliao]
                hs=1
                if (dset1i["\u4e32\u884c\u884c\u4f4d\u6570"].iloc[0]==3):
                    if ordanzi["\u7535\u538b"].iloc[0]<=19:
                        hs=1
                    elif ordanzi["\u7535\u538b"].iloc[0]>19 and ordanzi["\u7535\u538b"].iloc[0]<=29:
                        hs=2
                    elif ordanzi["\u7535\u538b"].iloc[0]>29 :
                        hs=3
                    else:
                        print("error:\u5355\u53f7"+str(dfdanzi[[i]])+"\u5bf9\u5e94\u4e32\u884c\u8001\u70bc\u677f"+str(fllbxh[i][l]))


                toadd=int(min(sij["\u8001\u70bc\u677f\u603b\u5de5\u4f4d\u6570"].iloc[l]*dset1i["\u5de5\u4f4d\u6700\u5927\u652f\u6570"].iloc[0]*dset0i["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u652f\u6570"].iloc[0]/(
                    hs*dset0i["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u6570"].iloc[0]),
                          tofenpei) )
                index=sij.index.tolist()[l]
                result.loc[index,"\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf"]=toadd
                zygw=math.ceil((toadd*
                              dset0i["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u6570"].iloc[0]*hs/(dset1i["\u5de5\u4f4d\u6700\u5927\u652f\u6570"].iloc[0]*dset0i["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u652f\u6570"].iloc[0])))

                if zygw==0:
                    zygw=1
                result.loc[index,"\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570"]=zygw
                tofenpei-=toadd
                result.loc[index,"\u5269\u4f59\u8bd5\u9a8c\u5c0f\u65f6"]=danzii["\u8bd5\u9a8c\u65f6\u95f4"].iloc[0]-24




    for j in range(len(dfshebei)):

        act123={}
        for key in njv123:
            if key[0]==dfshebei[j] :
                act123[(dfshebei[j],key[1],key[2])]=njv123[key].solution_value()*key[2]

        yiyong=[]
        sb=result[result["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j]]
        qwzall=dset2[dset2["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j]]["\u533a\u4f4d\u7ec4"].unique().tolist()
        qwzdianya=[[] for i in range(len(qwzall))]
        for i in range(len(qwzall)):
            qwzdianya[i]=[qwzall[i],0]


        dh=sb["\u4efb\u52a1\u5355\u53f7"].unique().tolist()


        for p in range(len(dh)):
            ordanzi=data[data["\u4efb\u52a1\u5355\u53f7"]==dh[p]]
            wuliao=ordanzi["\u7269\u6599\u7f16\u7801"].iloc[0]
            dset0i=dset0[dset0["\u7269\u6599\u7f16\u7801"]==wuliao]
            sj=sb[sb["\u4efb\u52a1\u5355\u53f7"]==dh[p]]
            for i in range(len(sj)):
                elem=sj["\u7535\u538b"].iloc[i]
                elema=sj["\u7535\u6d41"].iloc[i]
                elemb=sj["\u8d1f\u7535\u538b"].iloc[i]
                index=sj.index.tolist()[i]
                for v in range(len(dfdianya[j])):
                    if ((dfdianya[j][v][0]==elem) and (elema==(dfdianya[j][v][1]))
                    and (dfdianya[j][v][2]==elemb)):
                        v0=tuple(dfdianya[j][v])
                        break
                flag0=False
                for zu123 in range(1,9):
                    if act123[(dfshebei[j],v0,zu123)]>0 :
                        flag=False
                        if zu123==1:
                            thejq=jqwz1[j]
                        elif zu123==2:
                            thejq=jqwz2[j]
                        elif zu123==3:
                            thejq=jqwz3[j]
                        elif zu123==4:
                            thejq=jqwz4[j]
                        elif zu123==5:
                            thejq=jqwz5[j]
                        elif zu123==6:
                            thejq=jqwz6[j]
                        elif zu123==7:
                            thejq=jqwz7[j]
                        elif zu123==8:
                            thejq=jqwz8[j]

                        for k in range(len(thejq)):
                            for l in range(len(dfqwzdianya[j])):
                                if dfqwzdianya[j][l][0]==thejq[k] and dfqwzdianya[j][l][1]==v0:
                                    dset2i=dset2[(dset2["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j])&(dset2["\u533a\u4f4d\u7ec4"]==thejq[k])]
                                    if dset2i["V_MAX"].iloc[0]<elem:
                                        continue
                                    result.loc[index,"\u533a\u4f4d\u7ec4\u6700\u5927\u7535\u538b"]=dset2i["V_MAX"].iloc[0]
                                    qw1=dset2i[(pd.isna(dset2i["\u533a\u4f4d\u7535\u538b"]))&(pd.isna(dset2i["\u533a\u4f4d\u7535\u6d41"]))&
                                               (pd.isna(dset2i["\u533a\u4f4d\u8d1f\u7535\u538b"]))]
                                    qw20=dset2i[(~pd.isna(dset2i["\u533a\u4f4d\u7535\u538b"]))|(~pd.isna(dset2i["\u533a\u4f4d\u7535\u6d41"]))
                                                |(~pd.isna(dset2i["\u533a\u4f4d\u8d1f\u7535\u538b"]))]
                                    qw20["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"]=pd.to_datetime(qw20["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"], format="mixed")

                                    qw2=qw20[qw20["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"]<=tend]
                                    qw = pd.concat([qw1, qw2])
                                    qw.sort_values("\u533a\u4f4d\u53f7",ascending=True,inplace=True)
                                    qwli=qw["\u533a\u4f4d\u53f7"].tolist()
                                    twoqw=False
                                    numqw=0
                                    for kkk in range(len(qw)-1):
                                        if  (qw['\u533a\u4f4d\u53f7'].iloc[kkk] in qwli) and (qw['\u533a\u4f4d\u53f7'].iloc[kkk+1] in qwli):
                                            twoqw=True
                                            numqw=kkk
                                            break
                                    for kkk in range(len(qw)):
                                        if (dset0i["\u5668\u4ef6\u5360\u533a\u4f4d\u6570"].iloc[0]==2) :
                                            if (twoqw==True and kkk==numqw and qw["\u533a\u4f4d\u53f7"].iloc[kkk] not in yiyong
                                            and qw["\u533a\u4f4d\u53f7"].iloc[kkk+1] not in yiyong):
                                                result.loc[index,"\u533a\u4f4d\u7ec4"]=thejq[k]
                                                result.loc[index,"\u533a\u4f4d"]=(str(qw["\u533a\u4f4d\u53f7"].iloc[kkk] )
                                                                        +','+str(qw["\u533a\u4f4d\u53f7"].iloc[kkk+1] ))
                                                yiyong.append(qw["\u533a\u4f4d\u53f7"].iloc[kkk]  )
                                                yiyong.append(qw["\u533a\u4f4d\u53f7"].iloc[kkk+1]  )

                                                flag=True
                                                flag0=True
                                                act123[(dfshebei[j],v0,zu123)]-=2
                                                break


                                        if qw["\u533a\u4f4d\u53f7"].iloc[kkk]  not in yiyong:
                                            result.loc[index,"\u533a\u4f4d\u7ec4"]=thejq[k]
                                            result.loc[index,"\u533a\u4f4d"]=qw["\u533a\u4f4d\u53f7"].iloc[kkk]
                                            yiyong.append(qw["\u533a\u4f4d\u53f7"].iloc[kkk]  )

                                            flag=True
                                            flag0=True
                                            act123[(dfshebei[j],v0,zu123)]-=1
                                            break
                                if flag:
                                    break
                            if flag:
                                break
                        if not flag:
                            for k in range(len(thejq)):
                                if thejq[k] not in dfqwzdianya[j] :
                                    for l in range(len(qwzall)):

                                        if  qwzdianya[l][0]==thejq[k] and (qwzdianya[l][1]==v0 or qwzdianya[l][1]==0):
                                            dset2i=dset2[(dset2["\u8bbe\u5907\u7f16\u7801"]==dfshebei[j])&(dset2["\u533a\u4f4d\u7ec4"]==thejq[k])]
                                            if dset2i["V_MAX"].iloc[0]<elem:
                                                continue
                                            result.loc[index,"\u533a\u4f4d\u7ec4\u6700\u5927\u7535\u538b"]=dset2i["V_MAX"].iloc[0]
                                            qw1=dset2i[(pd.isna(dset2i["\u533a\u4f4d\u7535\u538b"]))&(pd.isna(dset2i["\u533a\u4f4d\u7535\u6d41"]))&
                                                       (pd.isna(dset2i["\u533a\u4f4d\u8d1f\u7535\u538b"]))]
                                            qw20=dset2i[(~pd.isna(dset2i["\u533a\u4f4d\u7535\u538b"])|~pd.isna(dset2i["\u533a\u4f4d\u7535\u6d41"])
                                                         |~pd.isna(dset2i["\u533a\u4f4d\u8d1f\u7535\u538b"]))]
                                            qw20["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"]=pd.to_datetime(qw20["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"], format="mixed")

                                            qw2=qw20[qw20["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"]<=tend]
                                            qw = pd.concat([qw1, qw2])
                                            qw.sort_values("\u533a\u4f4d\u53f7",ascending=True,inplace=True)
                                            qwli=qw["\u533a\u4f4d\u53f7"].tolist()
                                            twoqw=False
                                            numqw=0
                                            for kkk in range(len(qw)-1):
                                                if  (qw['\u533a\u4f4d\u53f7'].iloc[kkk] in qwli) and (qw['\u533a\u4f4d\u53f7'].iloc[kkk+1] in qwli):
                                                    twoqw=True
                                                    numqw=kkk
                                                    break
                                            for kkk in range(len(qw)):
                                                if (dset0i["\u5668\u4ef6\u5360\u533a\u4f4d\u6570"].iloc[0]==2) :
                                                    if (twoqw==True and kkk==numqw and qw["\u533a\u4f4d\u53f7"].iloc[kkk] not in yiyong
                                                    and qw["\u533a\u4f4d\u53f7"].iloc[kkk+1] not in yiyong):
                                                        result.loc[index,"\u533a\u4f4d\u7ec4"]=thejq[k]
                                                        result.loc[index,"\u533a\u4f4d"]=(str(qw["\u533a\u4f4d\u53f7"].iloc[kkk] )
                                                                                +','+str(qw["\u533a\u4f4d\u53f7"].iloc[kkk+1] ))
                                                        yiyong.append(qw["\u533a\u4f4d\u53f7"].iloc[kkk]  )
                                                        yiyong.append(qw["\u533a\u4f4d\u53f7"].iloc[kkk+1]  )

                                                        flag=True
                                                        flag0=True
                                                        act123[(dfshebei[j],v0,zu123)]-=2
                                                        qwzdianya[l][1]=v0
                                                        break

                                                if qw["\u533a\u4f4d\u53f7"].iloc[kkk]  not in yiyong:
                                                    result.loc[index,"\u533a\u4f4d\u7ec4"]=thejq[k]
                                                    result.loc[index,"\u533a\u4f4d"]=qw["\u533a\u4f4d\u53f7"].iloc[kkk]
                                                    yiyong.append(qw["\u533a\u4f4d\u53f7"].iloc[kkk]  )
                                                    flag=True
                                                    flag0=flag
                                                    act123[(dfshebei[j],v0,zu123)]-=1

                                                    qwzdianya[l][1]=v0
                                                    break
                                if flag:
                                    break

                    if flag0:
                        break



    result=result[result["\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf"]>0]


    llbyiyong=[]
    for i in range(len(result)):
        llbyiyong.append(result["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[i])
    busyllb=dset1[(dset1["\u8001\u70bc\u677f\u72b6\u6001"]=="\u8001\u70bc\u4e2d")]
    for i in range(len(busyllb)):
        dset2i=dset2[dset2["\u5bf9\u5e94\u8001\u70bc\u677f"]==busyllb["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[i]]
        if len(dset2i)==0:
            print("\u8001\u70bc\u4e2d\u7684\u8001\u70bc\u677f"+str(busyllb["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[i])+"\u627e\u4e0d\u5230\u5bf9\u5e94\u533a\u4f4d")
            continue
        if (pd.to_datetime(dset2i["\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4"].iloc[0], format="mixed")-t0).days>1:
            llbyiyong.append(busyllb["\u8001\u70bc\u677f\u7f16\u53f7"].iloc[i])





    llbyiyong=pd.DataFrame(llbyiyong)

    result.to_excel(target+"schedule_day_"+str(day)+".xlsx")
    llbyiyong.to_excel(target+"occupied_boards.xlsx")

    return result,llbyiyong

def inistatemain(day,base_ability,base_board,base_area,base_equ,base_data,target,t0):
    writer = pd.ExcelWriter(target+'state_day_'+str(day)+'.xlsx')

    startDate = (t0+datetime.timedelta(days=1)).strftime("%Y-%m-%d, %H:%M:%S")
    endDate = add_days(startDate, 1)
    if day==8:
        print("wait")
    writer = initStatus(writer, endDate,base_ability,base_board,base_area,base_equ,base_data)
    base_board.to_excel(excel_writer=writer, index=None, sheet_name='\u8001\u70bc\u677f')
    base_ability.to_excel(excel_writer=writer, index=None, sheet_name='\u8001\u70bc\u80fd\u529b')
    writer.close()

def mergeBoard(startDate, day, result, task_all, totalTask, target):
    secondDayTask = copy.deepcopy(task_all)
    base_ability = pd.read_excel(target+'state_day_'+str(day)+'.xlsx', '\u8001\u70bc\u80fd\u529b', dtype={'\u7269\u6599\u7f16\u7801': 'str', '\u8001\u70bc\u677f\u578b\u53f7': 'str'})
    base_board = pd.read_excel(target+'state_day_'+str(day)+'.xlsx', '\u8001\u70bc\u677f', dtype={'\u8001\u70bc\u677f\u578b\u53f7': 'str'})
    base_equ = pd.read_excel(target+'state_day_'+str(day)+'.xlsx', '\u8001\u70bc\u8bbe\u5907', dtype={'\u8bbe\u5907\u7f16\u7801': 'str'})
    base_area = pd.read_excel(target+'state_day_'+str(day)+'.xlsx', '\u8001\u70bc\u8bbe\u5907\u533a\u4f4d', dtype={'\u8bbe\u5907\u7f16\u7801': 'str'})
    pre_result = copy.deepcopy(result[result['\u7b2c\u5929\u6570'] < day])
    final_result = copy.deepcopy(result[result['\u7b2c\u5929\u6570'] == day])
    final_result['\u5206\u914d\u8ba2\u5355\u6570\u91cf'] = final_result['\u5206\u914d\u8ba2\u5355\u6570\u91cf'].apply(lambda x: np.around(x,))
    final_result['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = final_result['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'].apply(lambda x: np.around(x,))
    final_result['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = final_result['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'].apply(lambda x: np.around(x,))
    final_result['\u5206\u914d\u8ba2\u5355\u6570\u91cf'] = final_result['\u5206\u914d\u8ba2\u5355\u6570\u91cf'].astype('int64')
    final_result['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = final_result['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'].astype('int64')
    final_result['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = final_result['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'].astype('int64')
    notFinishList = []
    for taskNo, data in final_result.groupby('\u4efb\u52a1\u5355\u53f7'):
        thisNum = data['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'].sum()
        totalNum = data.iloc[0]['\u8ba2\u5355\u603b\u91cf']
        if thisNum < totalNum:
            notFinishList.append(taskNo)

    notFinishTask = secondDayTask[secondDayTask['\u4efb\u52a1\u5355\u53f7'].isin(notFinishList)]
    otherTask = secondDayTask[secondDayTask['\u4efb\u52a1\u5355\u53f7'].isin(notFinishList) == False].copy()
    partAbility = base_ability[['\u7269\u6599\u7f16\u7801','\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u652f\u6570','\u8001\u70bc\u677f\u578b\u53f7']]
    otherTask.sort_values(by=['\u7d27\u6025\u72b6\u6001', '\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4', '\u65f6\u95f4'], ascending=[False, True, False], inplace=True)
    secondDayTask = pd.concat([notFinishTask, otherTask], ignore_index=True)
    secondDayTask['\u6e29\u5ea6'] = secondDayTask['\u6e29\u5ea6'].fillna('25℃')
    secondDayTask['\u7535\u538b'] = secondDayTask['\u7535\u538b'].fillna('0V')
    secondDayTask['\u7535\u538b'] = secondDayTask['\u7535\u538b'].apply(lambda x: x.split('V')[0].split('v')[0])
    secondDayTask['\u7535\u538b'] = secondDayTask['\u7535\u538b'].apply(
        lambda x: float((x.split('K')[0]).split('k')[0]) * 1000 if 'K' in str(x) or 'k' in str(x) else x)
    secondDayTask['\u65f6\u95f4'] = secondDayTask['\u65f6\u95f4'].apply(lambda x: int(x.split('h')[0]))
    secondDayTask['\u6e29\u5ea6'] = secondDayTask['\u6e29\u5ea6'].apply(lambda x: int(x.split('℃')[0]))
    mergeTask = pd.merge(secondDayTask, partAbility, on=['\u7269\u6599\u7f16\u7801', '\u7269\u6599\u7f16\u7801'])
    mergeTask['\u7535\u538b'] = mergeTask['\u7535\u538b'].astype('str')

    fit_result = final_result[final_result['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] < final_result['\u8001\u70bc\u677f\u603b\u5de5\u4f4d\u6570']]
    if not fit_result.empty:
        canMergeGroup = fit_result.groupby(['\u6e29\u5ea6', '\u7535\u538b', '\u8d1f\u7535\u538b', '\u8001\u70bc\u677f\u578b\u53f7', '\u5269\u4f59\u8bd5\u9a8c\u5c0f\u65f6'])
        muban = pd.read_excel("merge_template.xlsx")
        addResult = pd.DataFrame(columns=muban.columns.values)
        for code, data in canMergeGroup:
            testTime = data.iloc[0]['\u5269\u4f59\u8bd5\u9a8c\u5c0f\u65f6'] + 24
            if testTime % 24 != 0:
                continue
            temperature = data.iloc[0]['\u6e29\u5ea6']
            voltage = data.iloc[0]['\u7535\u538b']
            nVoltage = data.iloc[0]['\u8d1f\u7535\u538b']
            boardType = data.iloc[0]['\u8001\u70bc\u677f\u578b\u53f7']
            boardNo = data.iloc[0]['\u8001\u70bc\u677f\u7f16\u53f7']
            fit_board = base_board[base_board['\u8001\u70bc\u677f\u7f16\u53f7'] == boardNo]
            maxBranchNum = fit_board.iloc[0]['\u5de5\u4f4d\u6700\u5927\u652f\u6570']
            if data.shape[0] == 1:
                taskNo = data.iloc[0]['\u4efb\u52a1\u5355\u53f7']
                totalTaskNum = data.iloc[0]['\u8ba2\u5355\u603b\u91cf']
                fit_task = final_result[final_result['\u4efb\u52a1\u5355\u53f7'] == taskNo]
                thisSum = fit_task['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'].sum()
                surplus = totalTaskNum - thisSum
                if surplus > 0:
                    print('+++++++\u8fd9\u884c\u4e0d\u5e94\u8be5\u663e\u793a\u5728\u63a7\u5236\u53f0\u4e0a++++++')
                else:
                    partCanTask = mergeTask[(mergeTask['\u6e29\u5ea6'].astype(int) == temperature) & (mergeTask['\u8001\u70bc\u677f\u578b\u53f7'].str.contains(boardType)) & (mergeTask['\u65f6\u95f4'].astype(int) == testTime)]
                    mergeTask, secondDayTask, addResult = fillBoard(partCanTask, startDate, voltage, nVoltage, maxBranchNum, data, mergeTask, secondDayTask, addResult)
            else:
                new_fit_data = copy.deepcopy(data)
                for index, row in data.iterrows():
                    row = data.loc[index]
                    if row['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] == 0:
                        continue
                    surplusStation = row['\u8001\u70bc\u677f\u603b\u5de5\u4f4d\u6570'] - row['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570']
                    if index in new_fit_data.index:
                        new_fit_data.drop(index=(index), inplace=True)
                    for insideIndex, insideRow in new_fit_data.iterrows():
                        if surplusStation >= insideRow['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570']:
                            if surplusStation == insideRow['\u8001\u70bc\u677f\u603b\u5de5\u4f4d\u6570']:
                                data.loc[index, '\u4efb\u52a1\u5355\u53f7'] = insideRow['\u4efb\u52a1\u5355\u53f7']
                                data.loc[index, '\u8ba2\u5355\u603b\u91cf'] = insideRow['\u8ba2\u5355\u603b\u91cf']
                                data.loc[index, '\u7d27\u6025\u5ea6'] = insideRow['\u7d27\u6025\u5ea6']

                                data.loc[index, '\u5269\u4f59\u5929\u6570'] = insideRow['\u5269\u4f59\u5929\u6570']
                                data.loc[index, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = insideRow['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570']
                                data.loc[index, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = insideRow['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf']

                                final_result.loc[index, '\u4efb\u52a1\u5355\u53f7'] = insideRow['\u4efb\u52a1\u5355\u53f7']
                                final_result.loc[index, '\u8ba2\u5355\u603b\u91cf'] = insideRow['\u8ba2\u5355\u603b\u91cf']
                                final_result.loc[index, '\u7d27\u6025\u5ea6'] = insideRow['\u7d27\u6025\u5ea6']
                                final_result.loc[index, '\u5269\u4f59\u5929\u6570'] = insideRow['\u5269\u4f59\u5929\u6570']
                                final_result.loc[index, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = insideRow['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570']
                                final_result.loc[index, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = insideRow['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf']

                            else:
                                addResult = append_row_data2(addResult, row, insideRow)
                            data.loc[insideIndex, '\u4efb\u52a1\u5355\u53f7'] = ''
                            data.loc[insideIndex, '\u5206\u914d\u8ba2\u5355\u6570\u91cf'] = 0
                            data.loc[insideIndex, '\u8ba2\u5355\u603b\u91cf'] = 0
                            data.loc[insideIndex, '\u7d27\u6025\u5ea6'] = 0
                            data.loc[insideIndex, '\u5269\u4f59\u5929\u6570'] = 0
                            data.loc[insideIndex, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = 0
                            data.loc[insideIndex, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = 0

                            final_result.loc[insideIndex, '\u4efb\u52a1\u5355\u53f7'] = ''
                            final_result.loc[insideIndex, '\u5206\u914d\u8ba2\u5355\u6570\u91cf'] = 0
                            final_result.loc[insideIndex, '\u8ba2\u5355\u603b\u91cf'] = 0
                            final_result.loc[insideIndex, '\u7d27\u6025\u5ea6'] = 0
                            final_result.loc[insideIndex, '\u5269\u4f59\u5929\u6570'] = 0
                            final_result.loc[insideIndex, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = 0
                            final_result.loc[insideIndex, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = 0

                            surplusStation = surplusStation - insideRow['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570']
                            data.loc[insideIndex, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = 0
                            data.loc[insideIndex, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = 0
                            new_fit_data.drop(index=(insideIndex), inplace=True)
                        elif surplusStation > 0:
                            everyBoardNum = insideRow['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] / insideRow['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570']
                            retainStationNum = insideRow['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] - surplusStation
                            insideRow['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = surplusStation
                            insideRow['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = surplusStation * everyBoardNum
                            final_result_num = final_result[(final_result['\u4efb\u52a1\u5355\u53f7'] == insideRow['\u4efb\u52a1\u5355\u53f7']) & (final_result.index <= index)]['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'].sum()
                            add_result_num = addResult[addResult['\u4efb\u52a1\u5355\u53f7'] == insideRow['\u4efb\u52a1\u5355\u53f7']]['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'].sum()
                            total_task_num = totalTask[totalTask['\u4efb\u52a1\u5355\u53f7'] == insideRow['\u4efb\u52a1\u5355\u53f7']].iloc[0]['\u8bd5\u9a8c\u6570\u91cf']
                            surplus_num = total_task_num - final_result_num - add_result_num
                            if surplusStation * everyBoardNum > surplus_num:
                                insideRow['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = surplus_num

                            retain_num = retainStationNum * everyBoardNum
                            if insideRow['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] < 10 or retain_num < 10:
                                continue
                            addResult = append_row_data2(addResult, row, insideRow)

                            if retain_num > total_task_num - final_result_num - add_result_num - insideRow['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf']:
                                retain_num = total_task_num - final_result_num - add_result_num - insideRow['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf']
                            new_fit_data.loc[insideIndex, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = retainStationNum
                            new_fit_data.loc[insideIndex, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = retain_num
                            final_result.loc[insideIndex, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = retainStationNum
                            final_result.loc[insideIndex, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = retain_num
                            data.loc[insideIndex, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = retainStationNum
                            data.loc[insideIndex, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = retain_num
                            new_fit_data.drop(index=(insideIndex), inplace=True)
                            surplusStation = 0
                        elif surplusStation == 0:
                            break
                    if surplusStation > 0:
                        partCanTask = mergeTask[(mergeTask['\u6e29\u5ea6'].astype('int') == temperature) & (
                            mergeTask['\u8001\u70bc\u677f\u578b\u53f7'].str.contains(boardType)) & (
                                                        mergeTask['\u65f6\u95f4'].astype('int') == testTime)]
                        df_temp = data.loc[data.index == index]
                        df_temp.loc[index, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = df_temp.loc[index, '\u8001\u70bc\u677f\u603b\u5de5\u4f4d\u6570'] - surplusStation
                        mergeTask, secondDayTask, addResult = fillBoard(partCanTask, startDate,
                                                                        voltage, nVoltage, maxBranchNum,
                                                                        df_temp,
                                                                        mergeTask, secondDayTask, addResult)
        emptyArea = final_result[final_result['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] == 0]
        for index, row in emptyArea.iterrows():
            thisBorad = base_board[base_board['\u8001\u70bc\u677f\u7f16\u53f7'] == row['\u8001\u70bc\u677f\u7f16\u53f7']]
            base_board.loc[thisBorad.index, '\u8001\u70bc\u677f\u72b6\u6001'] = '\u7a7a\u95f2'

        for index, row in emptyArea.iterrows():
            haveSameGroupResult = final_result[(final_result['\u8bbe\u5907\u7f16\u7801'] == row['\u8bbe\u5907\u7f16\u7801']) & (final_result['\u533a\u4f4d\u7ec4'] == row['\u533a\u4f4d\u7ec4']) & (final_result['\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] > 0)]
            temperature = row['\u6e29\u5ea6']
            voltage = row['\u7535\u538b']
            nVoltage = row['\u8d1f\u7535\u538b']
            testTime = row['\u5269\u4f59\u8bd5\u9a8c\u5c0f\u65f6'] + 24
            equ = base_equ[base_equ['\u8bbe\u5907\u7f16\u7801'] == row['\u8bbe\u5907\u7f16\u7801']]
            equType = equ.iloc[0]['\u8001\u70bc\u8bbe\u5907\u7c7b\u578b']
            board = base_board[base_board['\u8001\u70bc\u8bbe\u5907\u7c7b\u578b'] == equType]
            specs = board['\u8001\u70bc\u677f\u578b\u53f7'].drop_duplicates()
            materialCode = set()
            for i, spec in specs.items():
                fit_ability = base_ability[(base_ability['\u8001\u70bc\u677f\u578b\u53f7'] is not np.nan) & (base_ability['\u8001\u70bc\u677f\u578b\u53f7'].str.contains(spec))]
                fit_ability['\u7269\u6599\u7f16\u7801'].apply(lambda x: materialCode.add(x))
            partFitTask = mergeTask[(mergeTask['\u7269\u6599\u7f16\u7801'].isin(materialCode)) & (mergeTask['\u6e29\u5ea6'] == temperature) & (mergeTask['\u65f6\u95f4'] == testTime)]
            minV = voltage - 5 if voltage > 5 else 0
            maxV = voltage + 5
            fitTask = None
            if haveSameGroupResult.empty:
                fitTask = partFitTask.copy()
            elif nVoltage == 0:
                nVoltageTask = partFitTask[(partFitTask['\u7535\u538b'].str.contains('±') == False) & (partFitTask['\u7535\u538b'].str.contains('-') == False)]
                fitTask = nVoltageTask[(nVoltageTask['\u7535\u538b'].astype(float) >= minV) & (nVoltageTask['\u7535\u538b'].astype(float) <= maxV)]
            else:
                if voltage != 0:
                    nVoltageTask = partFitTask[(partFitTask['\u7535\u538b'].str.contains('±'))]
                    fitTask = nVoltageTask[(nVoltageTask['\u7535\u538b'].str.replace('±', '').astype(float) >= minV) & (
                                nVoltageTask['\u7535\u538b'].str.replace('±', '').astype(float) <= maxV)]
                else:
                    nVoltageTask = partFitTask[(partFitTask['\u7535\u538b'].str.contains('-'))]
                    fitTask = nVoltageTask[(nVoltageTask['\u7535\u538b'].str.replace('-', '').astype('float') >= nVoltage - 5) & (
                                nVoltageTask['\u7535\u538b'].str.replace('-', '').astype(float) <= nVoltage + 5)]

            if fitTask.empty:
                fitArea = base_area[(base_area['\u8bbe\u5907\u7f16\u7801'] == row['\u8bbe\u5907\u7f16\u7801']) & (base_area['\u533a\u4f4d\u53f7'] == row['\u533a\u4f4d'])]
                base_area.loc[fitArea.index, '\u533a\u4f4d\u72b6\u6001'] = '\u7a7a\u95f2'
                base_area.loc[fitArea.index, '\u533a\u4f4d\u7535\u538b'] = ''
                base_area.loc[fitArea.index, '\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4'] = ''
                base_area.loc[fitArea.index, '\u5bf9\u5e94\u8001\u70bc\u677f'] = ''
                final_result.drop(index=(index), inplace=True)

            else:
                oneTask = None
                for i, r in fitTask.iterrows():
                    split = r['\u8001\u70bc\u677f\u578b\u53f7'].split(',')
                    fitBoard = base_board[(base_board['\u8001\u70bc\u677f\u578b\u53f7'].isin(split)) & (base_board['\u8001\u70bc\u677f\u72b6\u6001'] == '\u7a7a\u95f2') & (base_board['\u8001\u70bc\u8bbe\u5907\u7c7b\u578b'] == equType)]
                    if not fitBoard.empty:
                        oneTask = fitTask[fitTask.index == i]
                        break
                if oneTask is None:
                    fitArea = base_area[(base_area['\u8bbe\u5907\u7f16\u7801'] == row['\u8bbe\u5907\u7f16\u7801']) & (base_area['\u533a\u4f4d\u53f7'] == row['\u533a\u4f4d'])]
                    base_area.loc[fitArea.index, '\u533a\u4f4d\u72b6\u6001'] = '\u7a7a\u95f2'
                    base_area.loc[fitArea.index, '\u533a\u4f4d\u7535\u538b'] = ''
                    base_area.loc[fitArea.index, '\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4'] = ''
                    base_area.loc[fitArea.index, '\u5bf9\u5e94\u8001\u70bc\u677f'] = ''
                    final_result.drop(index=(index), inplace=True)
                    continue
                selectBoard = fitBoard[fitBoard['\u53ef\u7528\u5de5\u4f4d\u6570'] == fitBoard['\u53ef\u7528\u5de5\u4f4d\u6570'].max()].head(1)
                fitArea = base_area[(base_area['\u8bbe\u5907\u7f16\u7801'] == row['\u8bbe\u5907\u7f16\u7801']) & (base_area['\u533a\u4f4d\u53f7'] == row['\u533a\u4f4d'])]
                base_area.loc[fitArea.index, '\u533a\u4f4d\u72b6\u6001'] = '\u8bd5\u9a8c\u4e2d'
                base_area.loc[fitArea.index, '\u533a\u4f4d\u7535\u538b'] = str(oneTask.iloc[0]['\u7535\u538b']).split('.0')[0] + 'V'
                base_area.loc[fitArea.index, '\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4'] = add_days(startDate, oneTask.iloc[0]['\u65f6\u95f4']/24 + day -1)
                base_area.loc[fitArea.index, '\u5bf9\u5e94\u8001\u70bc\u677f'] = selectBoard.iloc[0]['\u8001\u70bc\u677f\u7f16\u53f7']
                base_board.loc[selectBoard.index, '\u8001\u70bc\u677f\u72b6\u6001'] = '\u8001\u70bc\u4e2d'
                testNum = oneTask.iloc[0]['\u8bd5\u9a8c\u6570\u91cf']
                realStationNum = selectBoard.iloc[0]['\u53ef\u7528\u5de5\u4f4d\u6570']
                final_result.loc[index, '\u4efb\u52a1\u5355\u53f7'] = oneTask.iloc[0]['\u4efb\u52a1\u5355\u53f7']
                final_result.loc[index, '\u8ba2\u5355\u603b\u91cf'] = testNum
                final_result.loc[index, '\u7d27\u6025\u5ea6'] = oneTask.iloc[0]['\u7d27\u6025\u72b6\u6001']
                final_result.loc[index, '\u8001\u70bc\u677f\u578b\u53f7'] = selectBoard.iloc[0]['\u8001\u70bc\u677f\u578b\u53f7']
                final_result.loc[index, '\u8001\u70bc\u677f\u7f16\u53f7'] = selectBoard.iloc[0]['\u8001\u70bc\u677f\u7f16\u53f7']
                final_result.loc[index, '\u8001\u70bc\u677f\u603b\u5de5\u4f4d\u6570'] = realStationNum
                surplusDay = calc_days(oneTask.iloc[0]['\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4'], startDate) - final_result.loc[index, '\u7b2c\u5929\u6570'] + 1
                final_result.loc[index, '\u5269\u4f59\u5929\u6570'] = surplusDay
                final_result.loc[index, '\u662f\u5426\u8d85\u65f6'] = 0 if surplusDay - oneTask.iloc[0]['\u65f6\u95f4']/24 >= 0 else 1
                everyStationDevNum = selectBoard.iloc[0]['\u5de5\u4f4d\u6700\u5927\u652f\u6570'] / oneTask.iloc[0]['\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u652f\u6570']
                useStationNum = testNum / everyStationDevNum
                allVoltage = str(oneTask.iloc[0]['\u7535\u538b']).split('.0')[0]
                if '±' in allVoltage:
                    voltage = float(allVoltage.replace('±', ''))
                    nVoltage = voltage
                elif '-' in allVoltage:
                    voltage = 0
                    nVoltage = float(allVoltage.replace('-', ''))
                else:
                    voltage = float(allVoltage)
                    nVoltage = 0
                if useStationNum <= realStationNum:
                    final_result.loc[index, '\u7535\u538b'] = voltage
                    final_result.loc[index, '\u8d1f\u7535\u538b'] = nVoltage
                    final_result.loc[index, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = useStationNum
                    final_result.loc[index, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = testNum
                    mergeTask.drop(index=(oneTask.index), inplace=True)
                    secondDayTask.drop(index=(secondDayTask.loc[secondDayTask['\u4efb\u52a1\u5355\u53f7'] == oneTask.iloc[0]['\u4efb\u52a1\u5355\u53f7']].index),inplace=True)
                    temperature = oneTask.iloc[0]['\u6e29\u5ea6']
                    boardType = selectBoard.iloc[0]['\u8001\u70bc\u677f\u578b\u53f7']
                    testTime = oneTask.iloc[0]['\u65f6\u95f4']
                    maxBranchNum = selectBoard.iloc[0]['\u5de5\u4f4d\u6700\u5927\u652f\u6570']
                    partCanTask = mergeTask[(mergeTask['\u6e29\u5ea6'].astype(int) == temperature) & (mergeTask['\u8001\u70bc\u677f\u578b\u53f7'].str.contains(boardType)) & (mergeTask['\u65f6\u95f4'].astype(int) == testTime)]
                    data = final_result.loc[final_result.index == index]
                    mergeTask, secondDayTask, addResult = fillBoard(partCanTask, startDate, voltage, nVoltage, maxBranchNum, data, mergeTask, secondDayTask, addResult)
                else:
                    final_result.loc[index, '\u7535\u538b'] = voltage
                    final_result.loc[index, '\u8d1f\u7535\u538b'] = nVoltage
                    final_result.loc[index, '\u5360\u7528\u8001\u70bc\u677f\u5de5\u4f4d\u6570'] = realStationNum
                    realTestNum = realStationNum * everyStationDevNum
                    final_result.loc[index, '\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'] = realTestNum
                    surplusNum = testNum - realTestNum
                    fitMergeTask = mergeTask[mergeTask['\u4efb\u52a1\u5355\u53f7'] == oneTask.iloc[0]['\u4efb\u52a1\u5355\u53f7']]
                    mergeTask.loc[fitMergeTask.index, '\u8bd5\u9a8c\u6570\u91cf'] = surplusNum
                    secondDayTask.loc[secondDayTask[secondDayTask['\u4efb\u52a1\u5355\u53f7'] == oneTask.iloc[0]['\u4efb\u52a1\u5355\u53f7']].index, '\u8bd5\u9a8c\u6570\u91cf'] = surplusNum

        thisResult = pd.concat([final_result, addResult], ignore_index=True)
        thisResult = mergeSameData(thisResult)
        totalResult = pd.concat([pre_result, thisResult], ignore_index=True)
        for code, data in totalResult.groupby('\u4efb\u52a1\u5355\u53f7'):
            totalNum = data['\u8ba2\u5355\u603b\u91cf'].max()
            distributionNum = data['\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf'].sum()
            totalResult.loc[data.index, '\u8ba2\u5355\u603b\u91cf'] = totalNum
            totalResult.loc[data.index, '\u5206\u914d\u8ba2\u5355\u6570\u91cf'] = distributionNum

        secondDayTask['\u7535\u538b'] = secondDayTask['\u7535\u538b'].apply(lambda x: str(x) + 'V')
        secondDayTask['\u65f6\u95f4'] = secondDayTask['\u65f6\u95f4'].apply(lambda x: str(x) + 'h')
        secondDayTask['\u6e29\u5ea6'] = secondDayTask['\u6e29\u5ea6'].apply(lambda x: str(x) + '℃')
        writer = pd.ExcelWriter(target+'state_day_'+str(day)+'.xlsx')
        useArea = base_area[base_area['\u533a\u4f4d\u72b6\u6001'] == '\u8bd5\u9a8c\u4e2d']
        euqCodeList = useArea['\u8bbe\u5907\u7f16\u7801'].drop_duplicates().values.tolist()
        closeEqu = base_equ[base_equ['\u8bbe\u5907\u7f16\u7801'].isin(euqCodeList) == False]
        base_equ.loc[closeEqu.index, '\u8bbe\u5907\u72b6\u6001'] = '\u5173\u673a'
        base_equ.loc[closeEqu.index, '\u8bbe\u5907\u6e29\u5ea6'] = ''
        base_equ.to_excel(excel_writer=writer, index=None, sheet_name='\u8001\u70bc\u8bbe\u5907')
        base_area.to_excel(excel_writer=writer, index=None, sheet_name='\u8001\u70bc\u8bbe\u5907\u533a\u4f4d')
        base_board.to_excel(excel_writer=writer, index=None, sheet_name='\u8001\u70bc\u677f')
        base_ability.to_excel(excel_writer=writer, index=None, sheet_name='\u8001\u70bc\u80fd\u529b')
        writer.close()
        print('-'*50, target+'\u4f18\u5316\u7ed3\u675f', '-'*50)
        return totalResult, secondDayTask
    else:
        return result, task_all
def initStatus(writer, endDate,base_ability,base_board,base_area,base_equ,base_data):
    use_area=base_area
    time_unit = 24
    base_equ_copy = base_equ.copy()
    use_area_copy = use_area.copy()
    fit_area_temp = use_area_copy.loc[use_area_copy['\u533a\u4f4d\u72b6\u6001'] == '\u8bd5\u9a8c\u4e2d']
    if not fit_area_temp.empty:
        fit_area = fit_area_temp.loc[fit_area_temp['\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4'] <= endDate+' 12:00:00']
        for i, row in fit_area.iterrows():
            use_area_copy.loc[i, '\u533a\u4f4d\u72b6\u6001'] = '\u7a7a\u95f2'
            use_area_copy.loc[i, '\u533a\u4f4d\u7535\u538b'] = nan
            use_area_copy.loc[i, '\u533a\u4f4d\u7535\u6d41'] = nan
            use_area_copy.loc[i, '\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4'] = nan
            use_area_copy.loc[i, '\u5bf9\u5e94\u8001\u70bc\u677f'] = nan
            fit_board = base_board.loc[base_board['\u8001\u70bc\u677f\u7f16\u53f7'] == row['\u5bf9\u5e94\u8001\u70bc\u677f']]
            base_board.loc[fit_board.index, '\u8001\u70bc\u677f\u72b6\u6001'] = '\u7a7a\u95f2'

    firstDayData = base_data[base_data['\u7b2c\u5929\u6570'] == 1]
    for i, row in firstDayData.iterrows():
        fit_use_area = use_area_copy.loc[(use_area_copy['\u8bbe\u5907\u7f16\u7801'] == row['\u8bbe\u5907\u7f16\u7801']) & (use_area_copy['\u533a\u4f4d\u53f7'].astype('str').isin(str(row['\u533a\u4f4d']).split(',')))]
        days = row['\u5269\u4f59\u8bd5\u9a8c\u5c0f\u65f6'] / time_unit
        use_area_copy.loc[fit_use_area.index, '\u533a\u4f4d\u72b6\u6001'] = '\u8bd5\u9a8c\u4e2d'
        voltage = row['\u7535\u538b']
        if row['\u8d1f\u7535\u538b'] != 0:
            if row['\u7535\u538b'] == 0:
                voltage = row['\u8d1f\u7535\u538b']
            elif row['\u7535\u538b'] == row['\u8d1f\u7535\u538b']:
                voltage = '±' + str(row['\u7535\u538b'])
        use_area_copy.loc[fit_use_area.index, '\u533a\u4f4d\u7535\u538b'] = str(voltage)+'V'
        use_area_copy.loc[fit_use_area.index, '\u533a\u4f4d\u7535\u6d41'] = str(row['\u7535\u6d41'])+'mA'
        use_area_copy.loc[fit_use_area.index, '\u8ba1\u5212\u53d6\u51fa\u65f6\u95f4'] = add_days(endDate, days)
        use_area_copy.loc[fit_use_area.index, '\u5bf9\u5e94\u8001\u70bc\u677f'] = row['\u8001\u70bc\u677f\u7f16\u53f7']

        fit_board = base_board.loc[base_board['\u8001\u70bc\u677f\u7f16\u53f7'] == row['\u8001\u70bc\u677f\u7f16\u53f7']]
        base_board.loc[fit_board.index, '\u8001\u70bc\u677f\u72b6\u6001'] = '\u8001\u70bc\u4e2d'
    groupByCode = use_area_copy.groupby('\u8bbe\u5907\u7f16\u7801')
    for code, value in groupByCode:
        fit_equ = value.loc[value['\u533a\u4f4d\u72b6\u6001'] == '\u8bd5\u9a8c\u4e2d']
        fit_base_equ = base_equ.loc[base_equ['\u8bbe\u5907\u7f16\u7801'] == code]
        if not fit_equ.empty:
            fit_first_day = firstDayData.loc[firstDayData['\u8bbe\u5907\u7f16\u7801'] == code]
            base_equ_copy.loc[fit_base_equ.index, '\u8bbe\u5907\u72b6\u6001'] = '\u5f00\u673a'
            if fit_first_day.empty:
                if fit_base_equ.iloc[0]['\u8bbe\u5907\u6e29\u5ea6'] is nan:
                    base_equ_copy.loc[fit_base_equ.index, '\u8bbe\u5907\u6e29\u5ea6'] = '25℃'
                else:
                    base_equ_copy.loc[fit_base_equ.index, '\u8bbe\u5907\u6e29\u5ea6'] = fit_base_equ.iloc[0]['\u8bbe\u5907\u6e29\u5ea6']
            else:
                base_equ_copy.loc[fit_base_equ.index, '\u8bbe\u5907\u6e29\u5ea6'] = str(fit_first_day.iloc[0]['\u6e29\u5ea6']) + '℃'
        else:
            base_equ_copy.loc[fit_base_equ.index, '\u8bbe\u5907\u6e29\u5ea6'] = ''
            base_equ_copy.loc[fit_base_equ.index, '\u8bbe\u5907\u72b6\u6001'] = '\u5173\u673a'
    base_equ_copy.to_excel(excel_writer=writer, index=None, sheet_name='\u8001\u70bc\u8bbe\u5907')
    use_area_copy.to_excel(excel_writer=writer, index=None, sheet_name='\u8001\u70bc\u8bbe\u5907\u533a\u4f4d')
    return writer


def add_days(startDate, days):
    date1 = datetime.datetime.strptime(startDate, "%Y-%m-%d, %H:%M:%S")
    newDate = (date1 + datetime.timedelta(days)).strftime("%Y-%m-%d, %H:%M:%S")
    return newDate

t0=pd.to_datetime('2021-01-20 12:00:00')
tend=t0+datetime.timedelta(days=1.5)


global M
day=0
muban=pd.read_excel("result_template.xlsx")
final_result=pd.DataFrame(columns=muban.columns.values)
final_result.set_index(["\u7d22\u5f15"], inplace=True)
target='1'


while True :

    if day==0:
        task_all=pd.read_excel('oracle.xlsx',0,dtype={"\u7269\u6599\u7f16\u7801":"str",'\u4efb\u52a1\u5355\u53f7':'str'})
        M=max(float(task_all["\u8bd5\u9a8c\u6570\u91cf"].max()+1),10000)

        task_all.drop_duplicates(subset='\u4efb\u52a1\u5355\u53f7', keep='first', inplace=True)
        task_all.index = range(len(task_all))

        base_ability = pd.read_excel('oracle.xlsx', '\u8001\u70bc\u80fd\u529b', header=0, dtype={'\u7269\u6599\u7f16\u7801': 'str', '\u8001\u70bc\u677f\u578b\u53f7': 'str'})

        base_ability["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u652f\u6570"]=base_ability["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u652f\u6570"].fillna(1)
        base_ability["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u6570"]=base_ability["\u5668\u4ef6\u5360\u7528\u5de5\u4f4d\u6570"].fillna(1)

        base_board = pd.read_excel('oracle.xlsx', '\u8001\u70bc\u677f',dtype={'\u8001\u70bc\u677f\u578b\u53f7':'str'})
        base_board["\u53ef\u7528\u5de5\u4f4d\u6570"]=base_board["\u53ef\u7528\u5de5\u4f4d\u6570"].fillna(0)

        base_equ = pd.read_excel('oracle.xlsx', '\u8bbe\u5907',dtype={'\u8bbe\u5907\u7f16\u7801':'str'} )
        base_area = pd.read_excel('oracle.xlsx', '\u8bbe\u5907\u533a\u4f4d',dtype={'\u8bbe\u5907\u7f16\u7801':'str'})
        base_ability.drop_duplicates(subset='\u7269\u6599\u7f16\u7801', keep='first', inplace=True)
    elif day>0:

        task_all.index = range(len(task_all))
        data_prev=copy.deepcopy(task_all)
        result1=copy.deepcopy(result0)
        task_all = scheduling0(day,result1,data_prev)
        task_all.drop_duplicates(subset='\u4efb\u52a1\u5355\u53f7', keep='first', inplace=True)
        task_all.index = range(len(task_all))
        if len(task_all)==0 or day>=28 :
            final_result.index = range(len(final_result))
            final_result.to_excel("schedule_all_days.xlsx")
            break
        if day==1:
            final_result.index = range(len(final_result))
            final_result.to_excel("schedule_day_one.xlsx")
        base_ability = pd.read_excel(target+'state_day_'+str(day)+'.xlsx', '\u8001\u70bc\u80fd\u529b', header=0, dtype={'\u7269\u6599\u7f16\u7801': 'str', '\u8001\u70bc\u677f\u578b\u53f71': 'str', '\u8001\u70bc\u677f\u578b\u53f72': 'str', '\u8001\u70bc\u677f\u578b\u53f73': 'str', '\u8001\u70bc\u677f\u578b\u53f74': 'str', '\u8001\u70bc\u677f\u578b\u53f75': 'str'})
        base_board = pd.read_excel(target+'state_day_'+str(day)+'.xlsx', '\u8001\u70bc\u677f',dtype={'\u8001\u70bc\u677f\u578b\u53f7':'str'})
        base_equ = pd.read_excel(target+'state_day_'+str(day)+'.xlsx', '\u8001\u70bc\u8bbe\u5907',dtype={'\u8bbe\u5907\u7f16\u7801':'str'} )
        base_area = pd.read_excel(target+'state_day_'+str(day)+'.xlsx', '\u8001\u70bc\u8bbe\u5907\u533a\u4f4d',dtype={'\u8bbe\u5907\u7f16\u7801':'str'})

    for i in task_all.index:
        wuliao=task_all.loc[i,"\u7269\u6599\u7f16\u7801"]
        baseab=base_ability[base_ability["\u7269\u6599\u7f16\u7801"]==wuliao]
        if len(baseab)==0:
            print("\u5220\u9664\u5355\u53f7"+str(task_all.loc[i,"\u4efb\u52a1\u5355\u53f7"])+"\u539f\u56e0\uff1a\u7269\u6599\u7f16\u7801\u5728\u8001\u70bc\u80fd\u529b\u8868\u4e2d\u7f3a\u5931")
            task_all=task_all.drop([i])

            continue
        li=baseab["\u8001\u70bc\u677f\u578b\u53f7"].iloc[0]
        llbxh=[]
        if type(li)==str and ',' in li:
            llbxh=(li.split(','))
        else:
            llbxh.append(str(li))
        if len(llbxh)==1 :
            if '1051' in llbxh or '1070' in llbxh:
                print("\u5220\u9664\u5355\u53f7"+str(task_all.loc[i,"\u4efb\u52a1\u5355\u53f7"])+"\u539f\u56e0\uff1a\u8001\u70bc\u677f\u578b\u53f7\u4e3a1051\u62161070")
                task_all=task_all.drop([i])
        elif len(llbxh)==2:
            if '1051' in llbxh and '1070' in llbxh:
                print("\u5220\u9664\u5355\u53f7"+str(task_all.loc[i,"\u4efb\u52a1\u5355\u53f7"])+"\u539f\u56e0\uff1a\u8001\u70bc\u677f\u578b\u53f7\u4e3a1051\u62161070")
                task_all=task_all.drop([i])


    task_all.index = range(len(task_all))

    base_ability0=copy.deepcopy(base_ability)
    base_board0=copy.deepcopy(base_board)
    base_area0=copy.deepcopy(base_area)
    base_equ0=copy.deepcopy(base_equ)
    task_all0=copy.deepcopy(task_all)

    daycal(day,task_all0,base_ability0,base_board0,base_equ0,base_area0)

    df=pd.read_excel('matching.xlsx',0,dtype={"\u8bbe\u5907\u7f16\u7801":"str","\u4efb\u52a1\u5355\u53f7":'str'})
    danzi=task_all0["\u4efb\u52a1\u5355\u53f7"].unique().tolist()
    df=df[df["\u4efb\u52a1\u5355\u53f7"].isin( danzi)]


    base_ability0=copy.deepcopy(base_ability)
    base_board0=copy.deepcopy(base_board)
    base_area0=copy.deepcopy(base_area)
    base_equ0=copy.deepcopy(base_equ)
    task_all0=copy.deepcopy(task_all)
    task_all0.to_excel("tasks_"+target+".xlsx")

    result0,llbyiyong0=scheduling2(day,df,base_ability0,base_board0,base_area0,base_equ0,task_all0,target,t0,tend)

    day+=1

    base_ability0=copy.deepcopy(base_ability)
    base_board0=copy.deepcopy(base_board)
    base_area0=copy.deepcopy(base_area)
    base_equ0=copy.deepcopy(base_equ)
    inistatemain(day,base_ability0,base_board0,base_area0,base_equ0,result0,target,t0)
    result0["\u7b2c\u5929\u6570"]=day
    final_result = pd.concat([final_result, result0])
    t0=(t0+datetime.timedelta(days=1))
    tend=(tend+datetime.timedelta(days=1))

    print("finish day"+str(day))


se=base_equ[base_equ["\u8001\u70bc\u8bbe\u5907\u7c7b\u578b"]=='\u591a\u529f\u80fd\u8001\u70bc\u7cfb\u7edf']
for i in range(len(se)):
    quwei=base_area[base_area["\u8bbe\u5907\u7f16\u7801"]==se["\u8bbe\u5907\u7f16\u7801"].iloc[i]]
    busy = quwei[~pd.isna(quwei["\u5bf9\u5e94\u8001\u70bc\u677f"])]
    for j in range(len(busy)):
        board=base_board[base_board["\u8001\u70bc\u677f\u7f16\u53f7"]==busy["\u5bf9\u5e94\u8001\u70bc\u677f"].iloc[j]]
        if board["\u8001\u70bc\u677f\u72b6\u6001"].iloc[0] !='\u8001\u70bc\u4e2d':
            print("sadferrorrr")

