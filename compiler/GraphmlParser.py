import xmltodict
import random
from collections import defaultdict
from typing import Literal, TypeAlias
from aiofile import async_open

Point: TypeAlias = dict[Literal['x', 'y'], int]


try:
    from .config import SCHEMA_DIRECTORY
    from .Logger import Logger
    from .PlatformManager import PlatformManager
    from .fullgraphmlparser.stateclasses import State
except ImportError:
    from compiler.fullgraphmlparser.stateclasses import State
    from compiler.config import SCHEMA_DIRECTORY
    from compiler.Logger import Logger
    from compiler.PlatformManager import PlatformManager
"""
    This class gets Berloga-graphml and returns States, Components, Transitions
    Returns:
        _type_: _description_
"""

TRANSTIONS_DISTANCE = 75


class GraphmlParser:

    def __init__(self, platform: str, ws):
        pass

    colors = ["#00a550", "#9999ff", "#faf74d", "#ffa500", "#5dded3"]

    systemSignalsAlias = {
        "entry": "onEnter",
        "exit": "onExit"
    }

    operatorAlias = {
        "!=": "notEquals",
        "==": "equals",
        ">": "greater",
        "<": "less",
        ">=": "greaterOrEqual",
        "<=": "lessOrEqual"
    }

    @staticmethod
    def _getArgs(component: str, method: str, args: list[str], platform: str):
        """
            функция, которая формирует аргументы в виде 
            объекта с учетом контекста платформы
        """
        nmethod: dict = PlatformManager.getPlatform(
            platform)["components"][component]["methods"][method]
        params = nmethod["parameters"]
        result = {}
        for i in range(len(args)):
            # Можно сделать проверку значений и типов
            result[params[i]["name"]] = args[i]

        return result

    @staticmethod
    async def getParentNode(group_node: dict) -> dict:
        # Здесб мы отделяем данные о супер-ноде от ее под-графа
        # Необходимое содержимое data: {y:GroupNode: { y:NodeLabel: [название состояния, ивенты],
        #                                              y:Geometry: {@y, @x, @width, @height} } }

        for data in group_node["data"]:
            if "y:ProxyAutoBoundsNode" in data.keys():
                data_node_with_info = data["y:ProxyAutoBoundsNode"]["y:Realizers"]

        return {
            '@id': group_node["@id"],
            'data': data_node_with_info
        }

    @staticmethod
    def randColor() -> str:
        """
        Gen hex-color;
        """
        def r(): return random.randint(0, 255)
        return '#%02X%02X%02X' % (r(), r(), r())

    @staticmethod
    def addStateToDict(state: dict, states_dict: dict, parent: str | None) -> None:
        if 'y:GenericNode' in state["data"]:
            node_type = 'y:GenericNode'
        else:
            node_type = 'y:GroupNode'

        states_dict[state["@id"]] = {}
        states_dict[state["@id"]]["type"] = node_type
        states_dict[state["@id"]]["parent"] = parent
        if "y:Geometry" in state["data"][node_type]:
            geometry = state["data"][node_type]["y:Geometry"]
            states_dict[state["@id"]]["geometry"] = {
                "x": int(float(geometry["@x"])),
                "y": int(float(geometry["@y"])),
                "width": int(float(geometry["@width"])),
                "height": int(float(geometry["@height"]))
            }
        else:
            states_dict[state["@id"]]["geometry"] = {
                "x": 0,
                "y": 0,
                "width": 0,
                "height": 0
            }
        try:
            states_dict[state["@id"]
                        ]["name"] = state["data"][node_type]["y:NodeLabel"][0]["#text"]
        except TypeError:
            pass

    @staticmethod
    async def getFlattenStates(xml: list[dict], states: list = [], states_dict: dict[str, dict[str, str]] = {}, nparent: str | None = None) -> tuple[list[dict[str, str | dict]], dict[str, dict[str, str]]]:
        for node in xml:
            if "graph" in node.keys():
                parent = await GraphmlParser.getParentNode(node)
                states.append(parent)
                GraphmlParser.addStateToDict(
                    parent, states_dict, parent=nparent)
                await GraphmlParser.getFlattenStates(node["graph"]["node"], states, states_dict, nparent=parent["@id"])

            else:
                GraphmlParser.addStateToDict(
                    node, states_dict, parent=nparent)
                states.append(node)
        return states, states_dict

    @staticmethod
    async def getEvents(state: dict, node_type: str, platform: str) -> list[dict[str, dict]]:
        str_events: str = state["data"][node_type]["y:NodeLabel"][1]["#text"]
        events: list[str] = str_events.split("\n")
        new_events: list[dict[str, list[dict] | dict[str, str]]] = []
        current_event: str = ""
        i = 0
        for ev in events:
            if "/" in ev:
                if "." in ev:
                    command = ev.split(".")
                    component = command[0]
                    method = command[1][:-1]
                    new_events.append({
                        "trigger": {
                            "component": component,
                            "method": method,
                        },
                        "do": []
                    })
                    current_dict = new_events[i]["do"]
                else:
                    current_event = ev[:-1].replace(' ', '')
                    new_events.append({
                        "trigger": {
                            "component": "System",
                            "method": GraphmlParser.systemSignalsAlias[current_event],
                        },
                        "do": []
                    })
                    current_dict = new_events[i]["do"]
                i += 1
                continue

            action_dict = {}
            action = ev.split(".")
            component = action[0]
            action_dict["component"] = component
            bracket_pos = action[1].find("(")
            method = action[1][:bracket_pos]
            action_dict["method"] = method
            # Переделать
            if bracket_pos != -1:
                args = action[1][bracket_pos+1:-1].split(",")
            if args != ['']:
                action_dict["args"] = GraphmlParser._getArgs(
                    component, method, args, platform)
            else:
                action_dict["args"] = {}
            current_dict.append(action_dict)
        return new_events

    @staticmethod
    async def getParentName(state: dict, states_dict: dict) -> str | None:
        id: str = state["@id"]

        return states_dict[id]["parent"]

    @staticmethod
    def checkValueType(value: str) -> dict:
        if "." in value:
            command = value.split(".")
            component = command[0]
            method = command[1]
            return {"type": "component",
                    "value": {
                        "component": component,
                        "method": method,
                        "args": {}
                    }}
        else:
            return {"type": "value",
                    "value": value}

    @staticmethod
    def getCondition(condition: str) -> dict | None:
        result = None
        if condition != "":
            condition = condition.replace("[", "").replace("]", "")
            condition = condition.split()
            lval = GraphmlParser.checkValueType(condition[0])
            operator = condition[1]
            rval = GraphmlParser.checkValueType(condition[2])

            result = {
                "type": GraphmlParser.operatorAlias[operator],
                "value": [lval, rval]
            }

        return result

    @staticmethod
    def calculateEdgePosition(count_actions: int, count_condtions: int, source_position: dict, target_position: dict, used_coordinates: defaultdict[tuple[float, float], Point]) -> dict[str, int]:
        x1, y1, w1, h1 = list(source_position.values())
        x2, y2, w2, h2 = list(target_position.values())

        nx = (x1 + x2) // 10 + (300 * (1 + count_condtions + count_actions))

        ny = (y1 + y2) // 1.1 // 2.5 * (1 + count_actions + count_condtions)
        for coord in list(used_coordinates.keys()):
            if ny < coord[1] + TRANSTIONS_DISTANCE and ny > coord[1] - TRANSTIONS_DISTANCE:
                if nx < coord[0] + TRANSTIONS_DISTANCE and nx > coord[1] - TRANSTIONS_DISTANCE:
                    ny += 200 * used_coordinates[coord]['x']
                    used_coordinates[coord]['x'] += 1
                nx += 200 * used_coordinates[coord]['y']
                used_coordinates[coord]['y'] += 1
                break
            if nx < coord[0] + TRANSTIONS_DISTANCE and nx > coord[1] - TRANSTIONS_DISTANCE:
                if ny < coord[1] + TRANSTIONS_DISTANCE and ny > coord[1] - TRANSTIONS_DISTANCE:
                    nx += 200 * used_coordinates[coord]['y']
                    used_coordinates[coord]['y'] += 1
                ny += 200 * used_coordinates[coord]['x']
                used_coordinates[coord]['x'] += 1
                break
        # if ny in used_coordinates[:][1]:
        #    ny += 150
        #   nx += 150

        used_coordinates[(nx, ny)]['x'] += 1
        used_coordinates[(nx, ny)]['y'] += 1
        return {"x": nx, "y": ny}

    # Get n0::n1::n2 str and return n2
    # @staticmethod
    # async def getNodeId(id: str) -> str:
    #    pos = id.rfind(":")
    #    node_id = id[pos + 1:]
    #    return node_id

    @staticmethod
    async def _parseAction(action: str, platform) -> dict:
        component, method = action.split('.')
        call_pos = method.find('(')
        # Переделать
        args = method[call_pos + 1:-1].split(',')
        method = method[:call_pos]
        if args == [""]:
            args = {}
        else:
            args = GraphmlParser._getArgs(component, method, args, platform)
        return {
            "component": component,
            "method": method,
            "args": args
        }

    @staticmethod
    async def getActions(actions: list[str], platform) -> list[dict]:
        """Функция получает список действий и возвращает их в нотации IDE Lapki.

        Args:
            actions (list[str]): список действий. 
            Пример: ["Счётчик.Прибавить(231)", "ОружиеЦелевое.АтаковатьЦель()"]

        Returns:
            list[dict]: список словарей [{
                                        "component": Счётчик,
                                        "method": "Прибавить",
                                        "args": ["231"]
                                    }]
        """
        result: list[dict] = []
        for action in actions:
            result.append(await GraphmlParser._parseAction(action, platform))
        return result

    @staticmethod
    async def getTransitions(triggers: list[dict], statesDict: dict, platform: str) -> tuple[list, str]:
        transitions = []
        initial_state = ""
        used_coordinates: defaultdict[tuple[float, float],
                                      Point] = defaultdict(lambda: {'x': 1, 'y': 1})
        for trigger in triggers:
            transition = {}
            try:
                transition["source"] = trigger["@source"]
                transition["target"] = trigger["@target"]

                label = trigger["data"]["y:PolyLineEdge"]["y:EdgeLabel"]["#text"]
                # condition может содержать условие, условия и действия, действия и пустую строку
                event, condition = label.split("/")
                t: list[str] = condition.strip().split('\n')
                if len(t) > 0 and t[0].startswith('['):
                    condition = t[0]
                    actions = t[1:]
                else:
                    condition = ''
                    if '' in t:
                        t.remove('')
                    actions = t
                actions = await GraphmlParser.getActions(actions, platform)
                component, method = event.split(".")
                transition["trigger"] = {
                    "component": component,
                    "method": method
                }
                transition["condition"] = GraphmlParser.getCondition(condition)
                source_geometry = statesDict[trigger["@source"]]["geometry"]
                target_geometry = statesDict[trigger["@target"]]["geometry"]
                transition["position"] = GraphmlParser.calculateEdgePosition(len(actions), 1 if condition else 0,
                                                                             source_geometry, target_geometry, used_coordinates)
                # transition['position'] = {
                #     'x': int(
                #         float(trigger["data"]["y:PolyLineEdge"]["y:Path"]["@sx"])) * 0.5 + 400,
                #     'y': int(
                #         float(trigger["data"]["y:PolyLineEdge"]["y:Path"]["@sy"])) * 4 + 20
                # }
                transition["do"] = actions
                transition["color"] = GraphmlParser.randColor()
                transitions.append(transition)
            except (AttributeError, KeyError):
                print('heereeee')
                initial_state = trigger["@target"]
        return transitions, initial_state

    @staticmethod
    async def getGeometry(id: str, states_dict: dict) -> dict:
        parent = states_dict[id]["parent"]
        current_parent = parent
        p_x = 0
        p_y = 0

        if parent is not None:
            #    while current_parent is not None:
            #        print("cur in cycle: ", current_parent)
            p_geometry = states_dict[current_parent]["geometry"]
            p_x += p_geometry['x']
            p_y += p_geometry['y']
        #        current_parent = states_dict[current_parent]['parent']
        geometry = states_dict[id]["geometry"]
        print("Parent: ", states_dict[id]["parent"], id)
        print("Parent geometry:", p_x, p_y)
        h = geometry["height"]
        w = geometry["width"]
        x = geometry["x"] - p_x
        y = geometry["y"] - p_y
        if p_y != 0 and parent is not None:
            y -= 300
            if x < 0:
                x = 100
            if y > 0:
                print('here')
                y = -50  # TODO Зависимость от количества триггеров
        print(x, y)

        return {
            "x": int(float(x)),
            "y": -int(float(y)),
            "width": int(float(w)),
            "height": int(float(h))
        }

    @staticmethod
    async def createStates(flattenStates: list[dict], states_dict: dict, platform: str) -> dict:
        try:
            states = {}
            for state in flattenStates:
                if state["@id"] == '':
                    continue
                new_state = {}
                id = state["@id"]
                node_type = states_dict[state["@id"]]["type"]
                new_state["name"] = states_dict[state["@id"]]["name"]
                new_state["events"] = await GraphmlParser.getEvents(state, node_type, platform)
                geometry = await GraphmlParser.getGeometry(state["@id"], states_dict)
                # states_dict[state["@id"]]["geometry"] = geometry
                new_state["bounds"] = geometry
                parent = await GraphmlParser.getParentName(state, states_dict)
                if parent is not None and parent != '':
                    new_state["parent"] = parent
                states[id] = new_state

            return states
        except Exception:
            await Logger.logException()
            return dict({})

    @staticmethod
    async def getComponents(platform: str) -> dict:
        result = {}
        components = PlatformManager.getPlatform(platform)
        if components is not None:
            components = components["components"]

            for component in components:
                result[component] = {}
                result[component]["type"] = component
                result[component]["parameters"] = {}

        return result

    @staticmethod
    async def parse(unprocessed_xml: str, platform: str):
        try:
            xml = xmltodict.parse(unprocessed_xml)
            Logger.logger.info(xml)
            graph = xml["graphml"]["graph"]
            nodes = graph["node"]
            triggers = graph["edge"]
            components = await GraphmlParser.getComponents(platform)
            flattenStates, states_dict = await GraphmlParser.getFlattenStates(nodes, states=[], states_dict={})
            states = await GraphmlParser.createStates(flattenStates, states_dict, platform)
            transitions, initial_state = await GraphmlParser.getTransitions(triggers, states_dict, platform)
            obj_initial_state = states[initial_state]
            init_x = obj_initial_state["bounds"]["x"] - 100
            init_y = obj_initial_state["bounds"]["y"] - 100
            return {"states": states,
                    "initialState": {
                        "target": initial_state,
                        "position": {
                            "x": init_x,
                            "y": init_y
                        }
                    },
                    "transitions": transitions,
                    "components": components,
                    "platform": platform,
                    "parameters": {}}
        except Exception:
            await Logger.logException()
