
import pulp as lp
import json
import argparse
from datetime import datetime
from pathlib import Path
try:
    import numpy as np
except ImportError:
    class _Array:
        def __init__(self, size):
            self.shape = (size,)
            self.data = [0.0] * size

        def reshape(self, rows, cols):
            if rows * cols != len(self.data):
                raise ValueError("cannot reshape array")
            self.shape = (rows, cols)
            return self

        def __getitem__(self, key):
            if isinstance(key, tuple):
                row, col = key
                return self.data[row * self.shape[1] + col]
            return self.data[key]

        def __setitem__(self, key, value):
            if isinstance(key, tuple):
                row, col = key
                self.data[row * self.shape[1] + col] = value
            else:
                self.data[key] = value

        def __repr__(self):
            return repr(self.data)

    class _NumpyFallback:
        @staticmethod
        def zeros(size):
            return _Array(int(size))

    np = _NumpyFallback()


INIT_JSON = 'input.json'

def save_to_json(data, submit_path):
    output_path = Path(submit_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
def Material_Composition(data, output_path="output.json"):
    prob = lp.LpProblem("Material_Composition", lp.LpMinimize)

    max_mineral_num = data['baseParam']['maxMineralNum']
    planning_horizon = data['baseParam']['planningHorizon']
    daily_production_weight = data['baseParam']['dailyProductionWeight']
    minimum_ratio_used = data['baseParam']['minimumRatioUsed']
    nmineral = len(data['environmentData']['mineral'])
    element_name_range = ['Ad', 'Vdaf', 'Vd','Sd', 'Y', 'G', 'Q', 'Cri','Csr']
    selection_type = 1
    nelement = len(element_name_range)
    ncons_element = len(data['elementRatio'])
    daily_weight=[]
    if daily_production_weight == None:
        daily_weight.append(0)
    else:
        daily_weight.append(float(daily_production_weight))
    print("max # mineral used: %s"%max_mineral_num)
    print("planning horizon: %s"%planning_horizon)
    print("daily production weight: %s"%daily_production_weight)
    print("# mineral: %s"%nmineral)
    print("# element %s"%nelement)
	

    mineral_range = range(nmineral)
    element_range = range(nelement + 1)
    element_cons_range = range(ncons_element)
    mineral_name_range = []

    mineral_element = np.zeros(nmineral * (nelement+1))
    mineral_element = mineral_element.reshape(nmineral, nelement+1)
    for i in mineral_range:
        for j in element_range:
            if j == nelement:
                ratio1 = data['environmentData']['mineral'][i]['Ad']
                ratio2 = data['environmentData']['mineral'][i]['Vd']

                if ratio1 != None and ratio2 != None:
                    ratio=round(100*ratio1/(100-ratio2),1)
                    mineral_element[i, nelement] =  float(ratio) / 100.0
                else:
                    mineral_element[i, nelement] = 0
            else:
                ratio = data['environmentData']['mineral'][i][element_name_range[j]]
                if ratio != None:
                    mineral_element[i, j] =  float(ratio) / 100.0
                else:
                    mineral_element[i, j] = 0

    mineral_ratio = lp.LpVariable.dicts('mineral_ratio', mineral_range, lowBound=0, cat='Integer')
    element_ratio = lp.LpVariable.dicts('element_ratio', element_range, lowBound=0)
    element_ratio_diff = lp.LpVariable.dicts('element_ratio_diff', element_cons_range, lowBound=0)
    mineral_num_diff = lp.LpVariable('element_ratio_diff', lowBound=0)
    mineral_used = lp.LpVariable.dicts('mineral_used', mineral_range, cat='Binary')

    quality_weights=[0 for i in range(ncons_element)]
    for row_index in element_cons_range:
        element_weight = data['elementRatio'][row_index]['weightRat']
        if element_weight == None:
            element_weight = 0
        quality_weights[row_index]=element_weight



    prob += lp.lpSum(mineral_ratio[i] for i in mineral_range)  == 100
    if selection_type != 2:
        prob += lp.lpSum(mineral_used[i] for i in mineral_range) <= max_mineral_num
    
    prob += mineral_num_diff >= max_mineral_num - lp.lpSum(mineral_used[i] for i in mineral_range)
    prob += mineral_num_diff >= lp.lpSum(mineral_used[i] for i in mineral_range) - max_mineral_num

    
    for i in mineral_range:
        prob += 100 * mineral_used[i] >= mineral_ratio[i]
        prob += mineral_used[i] <=100000* mineral_ratio[i]

    for j in element_range:
        prob += element_ratio[j] == lp.lpSum(mineral_ratio[i] * mineral_element[i, j] for i in mineral_range)
	
    element_opt1=[]
    element_name2=[]
    for row_index in element_cons_range:
        element_name = data['elementRatio'][row_index]['elementProject']
        element_name2.append(element_name)
        element_lb = data['elementRatio'][row_index]['elementLb']
        element_ub = data['elementRatio'][row_index]['elementUb']
        element_opt = data['elementRatio'][row_index]['elementOpt']
        if element_lb == None:
            element_lb = -500
        if element_ub == None:
            element_ub = 500
        if element_opt == None:
            element_opt = element_lb
        if element_opt == None:
            element_opt1.append(0)
        else:
            element_opt1.append(float(element_opt)) 

        element_params = np.zeros(nelement+1)
        if element_name == 'Admax':
            element_params[-1] = 0.602
            
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) + 4.99  <= element_ub
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)+4.99  >= element_lb
            
            if element_opt != '':
                prob += element_ratio_diff[row_index] >= lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)+4.99 - element_opt
                prob += element_ratio_diff[row_index] >= element_opt - (lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)+4.99)
                 
        elif element_name == 'Sdmax':
            element_params[3] = 0.0845
            
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) + 0.030  <= element_ub
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) +0.030 >= element_lb

            if element_opt != '':
                prob += element_ratio_diff[row_index] >= lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) - element_opt
                prob += element_ratio_diff[row_index] >= element_opt - lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)
            
        elif element_name == 'M40':
            element_params[5] = 0.0695
            element_params[6] = 0.0180
            
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) + 82.28  <= element_ub
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) +82.28 >= element_lb
            if element_opt != '':
                prob += element_ratio_diff[row_index] >= lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)
                prob += element_ratio_diff[row_index] >= - lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)
            
        elif element_name == 'M10':
            
            element_params[5] =-0.0439
            element_params[6] = -0.0027
            
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) + 10.08  <= element_ub
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) +10.08 >= element_lb

            if element_opt != '':
                prob += element_ratio_diff[row_index] >= lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) - element_opt
                prob += element_ratio_diff[row_index] >= element_opt - lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)
            
        elif element_name == 'Crimax':
            element_params[7] = 0.468
            
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) + 11.43  <= element_ub
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)+11.43  >= element_lb
            if element_opt != '':
                prob += element_ratio_diff[row_index] >= lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) - element_opt
                prob += element_ratio_diff[row_index] >= element_opt - lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)
            
        elif element_name == 'Csrmin':
            element_params[8] = 0.466
            
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) +38.45 <= element_ub
            prob += lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) +38.45  >= element_lb
            
            if element_opt != '':
                prob += element_ratio_diff[row_index] >= lp.lpSum(element_params[j] * element_ratio[j] for j in element_range) - element_opt
                prob += element_ratio_diff[row_index] >= element_opt - lp.lpSum(element_params[j] * element_ratio[j] for j in element_range)
        print("element_params: %s, element_name: %s, element_lb: %s, element_ub: %s"%(element_params, element_name, element_lb, element_ub), "\n")

    inventory = []
    lb = []
    ub = []
    price = []
    mineral_used_initial = []
    element_Ad=[]
    element_Sd=[]
    element_Vdaf=[]
    element_Vd=[]
    element_Y=[]
    element_G=[]
    element_Q=[]
    element_Cri=[]
    element_Csr=[]
    selection = False
    print("selection_type: %s"%selection_type)
	
    for row_index in mineral_range:
        mineral_name_range.append(data['environmentData']['mineral'][row_index]['materialName'])
        row_inventory = data['environmentData']['mineral'][row_index]['materialInv']
        row_used = data['environmentData']['mineral'][row_index]['matSelect']
        row_lb = data['environmentData']['mineral'][row_index]['materialLb']
        row_ub = data['environmentData']['mineral'][row_index]['materialUb']
        row_price=data['environmentData']['mineral'][row_index]['materialPri']
        row_element_Ad=data['environmentData']['mineral'][row_index]['Ad']
        row_element_Vdaf=data['environmentData']['mineral'][row_index]['Vdaf']
        row_element_Vd=data['environmentData']['mineral'][row_index]['Vd']
        row_element_Sd=data['environmentData']['mineral'][row_index]['Sd']
        row_element_Y=data['environmentData']['mineral'][row_index]['Y']
        row_element_G=data['environmentData']['mineral'][row_index]['G']
        row_element_Q=data['environmentData']['mineral'][row_index]['Q']
        row_element_Cri=data['environmentData']['mineral'][row_index]['Cri']
        row_element_Csr=data['environmentData']['mineral'][row_index]['Csr']
        
        if row_element_Ad == None:
            element_Ad.append(0)
        else:
            element_Ad.append(float(row_element_Ad))
        if row_element_Vdaf == None:
            element_Vdaf.append(0)
        else:
            element_Vdaf.append(float(row_element_Vdaf))
        if row_element_Vd == None:
            element_Vd.append(0)
        else:
            element_Vd.append(float(row_element_Vd)) 
        if row_element_Sd == None:
            element_Sd.append(0)
        else:
            element_Sd.append(float(row_element_Sd))
        if row_element_Y == None:
            element_Y.append(0)
        else:
            element_Y.append(float(row_element_Y))
        if row_element_G == None:
            element_G.append(0)
        else:
            element_G.append(float(row_element_G))
        if row_element_Q == None:
            element_Q.append(0)
        else:
            element_Q.append(float(row_element_Q))
        if row_element_Cri == None:
            element_Cri.append(0)
        else:
            element_Cri.append(float(row_element_Cri))
        if row_element_Csr == None:
            element_Csr.append(0)
        else:
            element_Csr.append(float(row_element_Csr))
        if row_price ==  None:
            price.append(0)
        else:
            price.append(row_price)
        if row_inventory == None:
            inventory.append(0)
        else:
            inventory.append(int(row_inventory))
        if row_lb == None:
            lb.append(0)
        else:
            lb.append(float(row_lb))
        if row_ub == None:
            ub.append(100)
        else:
            ub.append(float(row_ub))
        if row_used == 'Y':
            selection = True
            mineral_used_initial.append(True)
        else:
            mineral_used_initial.append(False)
    
    for i in mineral_range:
        prob += lp.lpSum(mineral_ratio[i]) * planning_horizon * daily_production_weight / 100.0 <= inventory[i]
        if lb[i] > 0:
            prob += mineral_ratio[i] >= lb[i]
        else:
            prob += mineral_ratio[i] >= mineral_used[i] * minimum_ratio_used
		
        prob += mineral_ratio[i] <= ub[i]
        if selection_type == 2 and selection == True:
            if mineral_used_initial[i] == True:
                prob += mineral_used[i] == 1
            else:
                prob += mineral_used[i] == 0
        elif selection_type == 1 and selection == True:
            if mineral_used_initial[i] == True:
                prob += mineral_used[i] == 1
    
    print("%s, %s, %s"%(inventory[i], lb[i], ub[i]))
    
    WQ=1
    WP=0
    opt_price = data['optimalObject']['bestPrice']
    opt_quality = data['optimalObject']['bestQuality']
    opt_integrate=data['optimalObject']['qualityWeight']
    PW=data['optimalObject']['priceWeight']
    QW=data['optimalObject']['qualityWeight']
    if opt_price =='Y':
        WQ=0
        WP=1
    elif opt_quality == 'Y':
        WQ=1
        WP=0
    elif opt_integrate == 'Y':
        WQ=QW
        WP=PW
        
    obj = lp.LpAffineExpression()
    obj += (lp.lpSum(WQ*quality_weights[i]*element_ratio_diff[i] for i in element_cons_range) + WQ*mineral_num_diff
    +lp.lpSum(WP*price[i]*mineral_ratio[i] for i in mineral_range )/100)
    prob += obj



    prob.solve(lp.PULP_CBC_CMD(msg=1, timeLimit=60))

    print("-" * 40 + "%s"%lp.LpStatus[prob.status] + "-" * 40)
    if lp.LpStatus[prob.status] == "Optimal":
        output_statue = 1
    else:
        output_statue = 0
    output_mineral_ratio = {}
    for i in mineral_range:
        output_mineral_ratio[mineral_name_range[i]] = int(mineral_ratio[i].varValue)
    output = {
        'statue': output_statue,
        'mineral_ratio': output_mineral_ratio}
    print(output)
    save_to_json(output, output_path)
    print("objective=", lp.value(prob.objective))

    for i in element_range:
        print("element ratio=",element_ratio[i].varValue)
    for row_index in element_cons_range:
        element_params = np.zeros(nelement+1)
        element_name = data['elementRatio'][row_index]['elementProject']
        element_ub = data['elementRatio'][row_index]['elementUb']
        element_lb = data['elementRatio'][row_index]['elementLb']

        if element_ub == None:
            element_ub = 500
        if element_name == 'Admax':
            element_params[-1] = 0.602
            print(element_name, lp.lpSum(element_params[j] * element_ratio[j].varValue for j in element_range) + 4.99,element_ub)
        
            
        elif element_name == 'Sdmax':
            element_params[3] = 0.0845
            print( element_name,lp.lpSum(element_params[j] * element_ratio[j].varValue for j in element_range) + 0.030,element_ub)
                                                              
        elif element_name == 'M40':
            element_params[5] = 0.0695
            element_params[6] = 0.0180
            print(element_name,lp.lpSum(element_params[j] * element_ratio[j].varValue for j in element_range) + 82.28 ,element_ub )
            
        elif element_name == 'M10':
            
            element_params[5] =-0.0439
            element_params[6] = -0.0027
            print(element_name, lp.lpSum(element_params[j] * element_ratio[j].varValue for j in element_range) + 10.08 ,element_ub )
            
        elif element_name == 'Crimax':
            element_params[7] = 0.468
            print(element_name,lp.lpSum(element_params[j] * element_ratio[j].varValue for j in element_range) + 11.43 ,element_ub)
        
        elif element_name == 'Csrmin':
            element_params[8] = 0.466
            print( element_name,lp.lpSum(element_params[j] * element_ratio[j].varValue for j in element_range) +38.45 ,element_lb)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(Path(__file__).resolve().parent / "input.json"), help="Input JSON file. Defaults to input.json.")
    parser.add_argument("--output-dir", default="outputs", help="Directory for non-overwriting outputs.")
    return parser.parse_args()


def resolve_input_path(raw_path, script_dir):
    input_path = Path(raw_path)
    if input_path.is_absolute():
        return input_path
    cwd_path = Path.cwd() / input_path
    if cwd_path.exists():
        return cwd_path
    script_path = script_dir / input_path
    if script_path.exists():
        return script_path
    package_path = script_dir.parent / input_path
    if package_path.exists():
        return package_path
    return script_path


def resolve_output_dir(raw_path):
    output_dir = Path(raw_path)
    if output_dir.is_absolute():
        return output_dir
    return Path.cwd() / output_dir


if __name__ == '__main__':
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    input_path = resolve_input_path(args.input, base_dir)
    with input_path.open('r', encoding='utf-8') as load_f:
        data = json.load(load_f)

    output_dir = resolve_output_dir(args.output_dir)
    output_path = output_dir / ("%s_result_%s.json" % (input_path.stem, datetime.now().strftime("%Y%m%d_%H%M%S")))

    Material_Composition(data, output_path=str(output_path))
    print("output:", output_path)
