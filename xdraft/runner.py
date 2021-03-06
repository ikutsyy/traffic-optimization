from sumolib import checkBinary  # noqa
import traci
import pandas as pd
import matplotlib.pyplot as plt
from scipy import integrate
import xml.etree.ElementTree as ET
import os
import numpy as np
import multiprocessing as mp

cccc = 0

NO_GUI = True
TRAFFIC_TYPES = ['car1', 'truck1', 'bike1']
pd.set_option('display.max_columns', None)
METRIC = 'meanSpeedRelative'
GRIDLOCK_PENALTY = 0.1

N_LIMIT = 3600
N = 2000

NO_SIM = True  # skip re-simulating

# Setup sumo
if NO_GUI:
    sumoBinary = checkBinary('sumo')
else:
    sumoBinary = checkBinary('sumo-gui')


# MAIN FUNCTION TO CALL SIMULATOR
# Input: params - 21 length long vector - definition below
# Returns: Health metric depending on that set above. A higher value for this is better.

def call_sim_parallel(dparams):
    global cccc
    cccc += len(dparams)
    print("Call number "+str(cccc))
    pool = mp.Pool(len(dparams))
    calls = [(x, "number_" + str(i)) for i, x in enumerate(dparams)]
    out = pool.map(call_sim_zipped,calls)
    pool.close()
    return np.array([[x] for x in out]) # Package into 2D array


def call_sim_zipped(zipped):
    return call_sim(*zipped)


def call_sim(params, name="test", network_type='intersection', early_stop=False):
    #print(str(params[0])+"    "+str(params[1]))
    ret_code = update_network(params,name)
    if not ret_code:
        return 0.0
    update_sumoconfig(name)
    grid_pen = go(name)
    grid_pen = grid_pen * GRIDLOCK_PENALTY
    return get_sum_stats(grid_pen, name)

def get_sum_stats(grid_pen, name, metric='meanSpeedRelative'):
    # metric = one of 'halting-ratio', 'meanTravelTime' or 'meanSpeedRelative'
    df = pd.read_xml("in_use_files/sum_" + str(name) + ".xml")[:-1]
    df = df.head(int(len(df) * 0.9)).tail(int(len(df) * 0.8))
    if metric == 'halting-ratio':
        df['halting-ratio'] = df['halting'] / df['running']
    metric_out = np.average(df[metric])
    print(metric_out, " - ", grid_pen, " = ", metric_out - grid_pen)

    return max(0, metric_out - grid_pen)


def set_session():
    global session
    session = True


def go(name):
    if os.path.isfile("in_use_files/sum_" + str(name) + ".xml"):
        os.remove("in_use_files/sum_" + str(name) + ".xml")
    cmd = [sumoBinary, "-c", "in_use_files/"+str(name)+".sumocfg", "--start", "--quit-on-end", "--no-warnings",
           "--summary", "in_use_files/sum_" + str(name) + ".xml", "--tripinfo-output", "in_use_files/tripinfo_" + str(name) + ".xml",
           "--time-to-teleport", "-1"]
    traci.start(cmd, label=name)
    conn = traci.getConnection(name)
    iterations = 0

    #last_inb_sp = -1
    #last_outb_sp = -1
    while conn.simulation.getMinExpectedNumber() > 0 and iterations<10000:
        conn.simulationStep()
        iterations += 1
        """if iterations % 500 == 0:
            cur_inb_sp = conn.edge.getLastStepMeanSpeed("end1_junction")
            cur_outb_sp = conn.edge.getLastStepMeanSpeed("junction_end1")

            if (cur_inb_sp == last_inb_sp and cur_outb_sp == last_outb_sp):
                print("Traffic Stabilized. Breaking...")
                conn.close()
                return 0
            else:
                last_outb_sp = cur_outb_sp
                last_inb_sp = cur_inb_sp
    print("---------------------"+str(iterations))"""
    conn.close()
    return 0


# total is total traffic flow on edge, ratios is ratio of proportions
# e.g. total flow of 10 and truck:car:bike ratio of 5:3:2 = 5 trucks, 3 cars, 2 bikes
# selected is which ratio element (by value)
def get_props_from_total(total, ratios, selected):
    return str(round(total * selected / sum(ratios), 5))

def update_sumoconfig(name):
    with open('./inter1.sumocfg','r') as f:
        s = f.read()
        s = s.replace("draft",str(name))
        with open("./in_use_files/"+str(name)+".sumocfg",'w+') as f2:
            f2.write(s)

def update_network(param_list, savename='test'):
    # Must have all routes flowing to stop it falling into just allowing the busiest lane to flow only.
    if 0 in param_list[0:4]:
        return False

    # Mock param list:
    try:
        assert len(param_list) == 21
    except:
        print("PARAMLIST:", param_list)

    """
    Params 0 - 3 = Traffic light setups - ratio values (are normalised before use!)
            Default phases are
            0: N->S and S->N
            1: E->W and W->E
            2: N->E and S->W
            3: W->N and E->S
    Params 4, 5 = Sigma and tau - see Krauss Model -  https://sumo.dlr.de/docs/Definition_of_Vehicles%2C_Vehicle_Types%2C_and_Routes.html
    Params 6, 7, 8 = Ratio of trucks (6) , cars (7) , bikes (8) (as whole-number ratios/parts).
    Params 9 to 20 (including 20) are matrix of flow probabilities for each source->dest; skipping the leading diagonal.
    Flow probability = probability of a vehicle being emitted in any one second, yields binomial -
    see: https://sumo.dlr.de/docs/Simulation/Randomness.html#flows_with_a_random_number_of_vehicles
    NB: Not modelled per lane so can have duplicate spawns of vehicle types; sumo handles these rare cases by dropping extra vehicles.
        (NB in the xml files, SUMO uses 1=North 2=East 3=West 4=South)
        9: N->E (i.e. 1->2) 10: N->S  11: N->W
        12: E->N  13: E->S  14: E->W
        15: S->N  16: S->E  17: S->W
        18: W->N  19: W->E  20: W->S

    """
    # print(list(zip(param_list,range(0,len(param_list)))))

    with open('./draft.rou.xml') as f:
        root = ET.parse(f)

        # Update probability of emissions ( = flow):
        flowdown = min(N_LIMIT, int(N / sum(param_list[9:])))
        for i, n in enumerate(root.iter('flow')):
            # i is the index of the specific ((source,dest),vehicle). There are 3 vehicle types.
            # k is the index into the parameters for the specific source->dest. These do not distinguish by vehicle,
            # so there are a third of the overall number of flows (i). So i = 3k (trucks) or 3k + 1 (cars) or 3k+2 (bikes)
            k = i // 3

            # First arg - the overall flow (sum of all vehicle types) which should be assigned to the flow. This is what
            # is passed in as a parameter for the specific flow - add 9 as this starts from index 9.
            # Second arg - the ratio values for the three types of vehicle.
            # Third arg - the ratio value for whichever of the vehicle types are currently being assigned - add 6 as this
            # starts form index 6. i - 3k = 1 or 2 or 3 i.e. the vehicle type.
            prob = get_props_from_total(param_list[9 + k], param_list[6:9], param_list[6 + i - (3 * k)])
            n.set('probability', prob)
            n.set('end', str(flowdown))
            # print(9+k, prob, param_list[9+k],n.attrib)

        # Set tau and sigma for all vTypes
        # for vType in root.findall('vType'):
        # print()
        # vType.set('sigma',str(param_list[4]))
        # vType.set('tau',str(param_list[5]))

        root.write("./in_use_files/" + str(savename) + ".rou.xml")

    # Update the traffic lights
    with open('./draft.net.xml') as f:
        root = ET.parse(f)
        zs = list(x for x in root.find('tlLogic') if 'y' not in x.get('state'))
        for i, phase in enumerate(zs):
            # print(phase.attrib, param_list[i], get_props_from_total(1,param_list[0:4],param_list[i]))
            phase.set('duration', get_props_from_total(60, param_list[0:4], param_list[i]))
        root.write("./in_use_files/" + str(savename) + ".net.xml")

    return True


# this is the main entry point of this script
if __name__ == "__main__":
    update_sumoconfig("test")
    go("test")
    get_sum_stats("test")
    """
    # this script has been called from the command line. It will start sumo as a
    # server, then connect and run
    if  NO_SIM: go()
    param_list = [99, 3, 106, 12,
                  0.5, 0.5,
                  1, 1, 1,
                  0.9, 0.9, 0.9, 0.9, 0.9, 0.45, 0.45, 0.45, 0.1, 0.1, 0.1, 0.1]
    update_network(param_list)
    go()"""
