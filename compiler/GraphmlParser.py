import xmltodict
import json
from aiofile import async_open

try:
    from .config import SCHEMA_DIRECTORY
    from .Logger import Logger
except ImportError:
    from compiler.config import SCHEMA_DIRECTORY
    from compiler.Logger import Logger
"""
    This class gets Berloga-graphml and returns States, Components, Transitions
    Returns:
        _type_: _description_
"""


class GraphmlParser:
    platforms = {}

    def __init__(self, platform: str, ws):
        pass

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
        nmethod: dict = GraphmlParser.platforms[platform]["components"][component]["methods"][method]
        keys = list(nmethod["parameters"].keys())
        result = {}
        for i in range(len(args)):
            # Можно сделать проверку значений и типов
            result[keys[i]] = args[i]

        return result

    @staticmethod
    async def initPlatform(filename: str, platform: str):
        """ 
        Функция для загрузки платформ (компонентов, сигналов)
        Принимает на вход название платформы
        Если такая платформа уже была инициализирована,
        повторной инициализации не происходит.
        """
        if platform not in GraphmlParser.platforms.keys():
            async with async_open(f"{SCHEMA_DIRECTORY}{filename}.json", "r") as f:
                data = await f.read()
                json_data: dict = json.loads(data)
            GraphmlParser.platforms[platform] = json_data["platform"][platform]

    @staticmethod
    async def getParentNode(group_node: dict) -> dict:
        return {
            '@id': group_node["@id"],
            'data': group_node["data"]
        }

    @staticmethod
    def addStateToDict(state: dict, states_dict: dict, parent: str) -> None:
        if 'y:GenericNode' in state["data"]:
            node_type = 'y:GenericNode'
        else:
            node_type = 'y:GroupNode'
        
        states_dict[state["@id"]] = {}
        states_dict[state["@id"]]["type"] = node_type
        states_dict[state["@id"]]["parent"] = parent
        try:
            states_dict[state["@id"]]["name"] = state["data"][node_type]["y:NodeLabel"][0]
        except TypeError:
            pass

    @staticmethod
    async def getFlattenStates(xml: list[dict], states: list = [], states_dict: dict[str, dict[str, str]] = {}, nparent='') -> tuple[list[dict[str, str | dict]], dict[str, dict[str, str]]]:
        for node in xml:
            if "graph" in node.keys():
                parent = await GraphmlParser.getParentNode(node)
                states.append(parent)
                GraphmlParser.addStateToDict(parent, states_dict, parent=nparent)        
                await GraphmlParser.getFlattenStates(node["graph"]["node"], states, states_dict, nparent=parent["@id"])
            else:
                GraphmlParser.addStateToDict(node, states_dict, parent=nparent)
                states.append(node)
        return states, states_dict

    @staticmethod
    async def getEvents(state: dict, node_type: str, platform: str) -> list[dict[str, dict]]:
        str_events: str = state["data"][node_type]["y:NodeLabel"][1]
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
    async def getParentName(state: dict, states_dict: dict) -> str:
        id: str = state["@id"]

        return states_dict[id]["parent"]

    @staticmethod
    async def checkValueType(value: str) -> dict:
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
    async def getCondition(condition: str) -> dict | None:
        result = None
        if condition != "":
            condition = condition.replace("[", "").replace("]", "")
            condition = condition.split()
            lval = await GraphmlParser.checkValueType(condition[0])
            operator = condition[1]
            rval = await GraphmlParser.checkValueType(condition[2])

            result = {
                "type": GraphmlParser.operatorAlias[operator],
                "value": [lval, rval]
            }

        return result

    @staticmethod
    async def calculateEdgePosition(source_position: dict, target_position: dict, used_coordinates: list) -> dict[str, int]:
        x1, y1, w1, h1 = list(source_position.values())
        x2, y2, w2, h2 = list(target_position.values())

        nx = x1 + w1 // 2
        ny = (y1 + y2 + h2) // 2

        while (nx, ny) in used_coordinates:
            ny += 100
            nx += 100
        used_coordinates.append((nx, ny))
        return {"x": nx, "y": ny}

    # Get n0::n1::n2 str and return n2
    @staticmethod
    async def getNodeId(id: str) -> str:
        pos = id.rfind(":")
        node_id = id[pos + 1:]
        return node_id

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
    async def getTransitions(triggers: dict, statesDict: dict, platform: str) -> tuple[list, str]:
        transitions = []
        initial_state = ""
        used_coordinates: list[tuple[int, int]] = []
        for trigger in triggers:
            transition = {}
            try:
                transition["source"] = await GraphmlParser.getNodeId(trigger["@source"])
                transition["target"] = await GraphmlParser.getNodeId(trigger["@target"])

                # condition может содержать условие, условия и действия, действия и пустую строку
                event, condition = trigger["y:EdgeLabel"].split("/")
                t = condition.strip().split('\n')
                condition = t[0]
                actions = t[1:]
                actions = await GraphmlParser.getActions(actions, platform)
                component, method = event.split(".")
                transition["trigger"] = {
                    "component": component,
                    "method": method
                }

                transition["condition"] = await GraphmlParser.getCondition(condition)
                source_geometry = statesDict[trigger["@source"]]["geometry"]
                target_geometry = statesDict[trigger["@target"]]["geometry"]
                transition["position"] = await GraphmlParser.calculateEdgePosition(source_geometry, target_geometry, used_coordinates)
                transition["do"] = actions
                transition["color"] = "#22a4f5"
                transitions.append(transition)
            except AttributeError as e:
                initial_state = trigger["@target"]

        return transitions, initial_state

    @staticmethod
    async def getGeometry(state: dict, type: str) -> dict:
        geometry = state["data"][type]["y:Geometry"]
        x = geometry['@x']
        y = geometry['@y']
        w = geometry['@width']
        h = geometry['@height']

        return {
            "x": int(float(y)) // 2,
            "y": int(float(x)) // 2,
            "width": int(float(h)),
            "height": int(float(w))
        }

    @staticmethod
    async def createStates(flattenStates: list[dict], states_dict: dict, platform: str) -> dict:
        try:
            states = {}
            for state in flattenStates:
                if state["@id"] == '':
                    continue
                new_state = {}
                id = await GraphmlParser.getNodeId(state["@id"])
                node_type = states_dict[state["@id"]]["type"]
                new_state["name"] = states_dict[state["@id"]]["name"]
                new_state["events"] = await GraphmlParser.getEvents(state, node_type, platform)
                geometry = await GraphmlParser.getGeometry(state, node_type)
                states_dict[state["@id"]]["geometry"] = geometry
                new_state["bounds"] = geometry
                parent = await GraphmlParser.getParentName(state, states_dict)
                if parent != "":
                    new_state["parent"] = parent
                states[id] = new_state

            return states
        except Exception:
            await Logger.logException()

    @staticmethod
    async def getComponents(platform: str) -> dict:
        result = {}
        components = GraphmlParser.platforms[platform]["components"].keys()

        for component in components:
            result[component] = {}
            result[component]["type"] = component
            result[component]["parameters"] = {}

        return result

    @staticmethod
    async def parse(unprocessed_xml: str, filename: str, platform: str):
        try:
            xml = xmltodict.parse(unprocessed_xml)
            await GraphmlParser.initPlatform(filename, platform)
            graph = xml["graphml"]["graph"]
            nodes = graph["node"]
            triggers = graph["edge"]
            components = await GraphmlParser.getComponents(platform)
            flattenStates, states_dict = await GraphmlParser.getFlattenStates(nodes, states=[], states_dict={})
            states = await GraphmlParser.createStates(flattenStates, states_dict, platform)
            transitions, initial_state = await GraphmlParser.getTransitions(triggers, states_dict, platform)
            return {"states": states,
                    "initialState": initial_state,
                    "transitions": transitions,
                    "components": components,
                    "platform": "BearlogaDefend",
                    "parameters": {}}
        except Exception:
            await Logger.logException()
