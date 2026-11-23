// Genuine Engineering-CAD Industrial Equipment & Robotic Arm Catalog
// Every entry below uses 1:1 manufacturer / engineering STEP CAD geometry — zero procedural primitive substitutes.
export const EQUIPMENT_GROUPS = [
  {
    title: "工业装备 · 真机 CAD 闭环操控",
    items: [
      {
        id: "sorting_line", file: "sorting_line", name: "智能视觉分拣流水线",
        height: 1.9, camera: [8.5, 4.5, 8.5], controllable: true,
        subtitle: "33 万顶点真机直辊筒线 CAD · 39 辊真转 + 光幕识别 + 摆臂分流联锁",
        pitch: "直辊筒输送线真机 CAD ×3 节 · 39 根独立动力辊转动 + 光幕扫掠 + 摆臂预判分流，支持决策模型闭环调度",
        specs: [["CAD 规模", "330,366 顶点 / 90 网格"], ["线体长度", "8.2 m"], ["安全联锁", "滑道满溢防堵 + 光幕握手"]],
        task: { name: "智能分拣闭环", goal: "扫描包裹并按类型下发分流或直通指令，避免滑道满溢", metric: "已分拣", target: 6, unit: "件" },
      },
      {
        id: "forklift", file: "forklift", name: "平衡重式智能叉车",
        height: 2.6, camera: [4.5, 3.2, 4.5], controllable: true,
        subtitle: "37 万面真机 CAD + 2K PBR 贴图 · 二级门架升降 + 高位禁行联锁",
        pitch: "真机工程 CAD + D/N/ORM 三通道 PBR 贴图 · 方向盘/液压管链/轮胎花纹全细节，内置高位禁行防倾翻联锁",
        specs: [["CAD 规模", "约 37 万三角面 + 2K PBR"], ["门架行程", "0 – 1.15 m (高位后倾 2.8°)"], ["安全联锁", "高位禁行 (<0.18m 方可行车)"]],
        task: { name: "托盘叉取上架", goal: "月台取托→低位安全行驶→货架高位举升落托", metric: "上架托盘", target: 3, unit: "托" },
      },
      {
        id: "kr210", file: "kr210", name: "KUKA KR210 重载六轴工位",
        height: 2.6, camera: [4.2, 2.8, 4.2], controllable: true,
        subtitle: "28 万顶点 KUKA 原厂级 CAD · 全六轴运动链 + 气动夹具点焊联锁",
        pitch: "210kg 重载六轴工业臂真机 CAD · 平衡缸/铸造筋/石墨腕段全细节，全六轴受决策模型闭环操控",
        specs: [["CAD 规模", "196,952 顶点"], ["自由度 / 负载", "6 轴 / 210 kg"], ["安全联锁", "气动夹具压紧确认点焊联锁"]],
        task: { name: "上料点焊闭环", goal: "抓取毛坯装入夹具，锁紧点焊后松夹下料", metric: "完工工件", target: 3, unit: "件" },
      },
      {
        id: "robot_cell", file: "robot_cell", name: "KUKA iiwa 14 精密装配台",
        height: 2.2, camera: [3.6, 2.4, 3.6], controllable: true,
        subtitle: "LBR iiwa 14 原厂真机 CAD · 七轴阻抗柔顺压装 + TCP 荧光轨迹",
        pitch: "七轴力控协作臂原厂 CAD · 曲面铝壳/KUKA 铭牌/ISO 9409 法兰螺栓全齐，支持限力柔顺压装闭环",
        specs: [["CAD 来源", "Drake / Menagerie 原厂 CAD"], ["自由度 / 负载", "7 轴 / 14 kg"], ["安全联锁", "同轴对中 + <18N 过载保护"]],
        task: { name: "柔顺精密压装", goal: "拾取壳体同轴对中，在接触力安全阈值内完成压装", metric: "装配总成", target: 3, unit: "件" },
      },
      {
        id: "voron_printer", file: "voron_printer", name: "Voron 2.4 工业增材整机",
        height: 2.4, camera: [3.4, 2.6, 3.4], controllable: true,
        partGroups: ["Gantry", "Z_Assembly", "Electronics", "Skirt", "Frame", "Bed_Components", "Panels", "Spool_Holder", "Exhaust_Filter_Assembly"],
        subtitle: "7,433 零件官方 241MB STEP 直转 · CoreXY 飞行龙门闭环控制",
        pitch: "工程 STEP 装配树保真直转（120 万顶点、7433 真实零件）· 九大总成可拆解，支持预热/四轴调平/挤出闭环控制",
        specs: [["CAD 规模", "7,433 零件 / 120 万顶点"], ["运动架构", "CoreXY 飞行龙门 + 四丝杠 QGL"], ["安全联锁", "230°C 防冷挤出 + 未调平禁打"]],
        task: { name: "闭环增材制造", goal: "预热热床喷头→CoreXY回零与四轴调平→高速挤出成型", metric: "成型零件", target: 3, unit: "件" },
      },
    ],
  },
  {
    title: "机械臂 · 原厂 CAD 拆解展台",
    items: [
      {
        id: "robot_panda", pose: [0, -0.45, 0, -2.15, 0, 1.75, 0.7854], robot: "panda", name: "Franka Emika Panda", file: "robot_panda",
        height: 2.4, camera: [3.6, 2.3, 3.6],
        subtitle: "7 轴力控协作臂 · 原厂 CAD 连杆树",
        pitch: "研究与精密装配标杆七轴臂 · 原厂 CAD 网格装配，11 个连杆部件可点击拆解",
        specs: [["自由度", "7 轴"], ["负载", "3 kg"], ["MuJoCo 工艺", "精密插装 / 上下料"], ["网格", "原厂 CAD"]],
      },
      {
        id: "robot_ur5e", pose: null, robot: "ur5e", name: "Universal Robots UR5e", file: "robot_ur5e",
        height: 2.4, camera: [3.6, 2.3, 3.6],
        subtitle: "Universal Robots 六轴工业协作臂 · 原厂 CAD",
        pitch: "协作机器人标杆机型 · 原厂缎面铝与 UR 蓝关节盖 CAD 网格",
        specs: [["自由度", "6 轴"], ["负载", "5 kg"], ["MuJoCo 工艺", "机床上下料 / 焊接打点"], ["网格", "原厂 CAD"]],
      },
      {
        id: "robot_xarm7", pose: [0, -0.5, -0.2, 0.6, 0, 1.2, 0], robot: "xarm7", name: "UFACTORY xArm7", file: "robot_xarm7",
        height: 2.4, camera: [3.6, 2.3, 3.6],
        subtitle: "UFACTORY 七轴工业臂 · 原厂 CAD",
        pitch: "七轴冗余自由度工业臂 · 含完整平行连杆夹爪原厂 CAD 拆解",
        specs: [["自由度", "7 轴"], ["负载", "5 kg"], ["MuJoCo 工艺", "真空拆垛 / 码垛下线"], ["网格", "原厂 CAD"]],
      },
      {
        id: "robot_gen3", pose: [0, -0.5, -0.2, 0.6, 0, 1.2, 0], robot: "gen3", name: "Kinova Gen3", file: "robot_gen3",
        height: 2.4, camera: [3.6, 2.3, 3.6],
        subtitle: "碳纤维七轴轻量臂 · 原厂 CAD",
        pitch: "碳纤维轻量臂 + 腕带视觉模组原厂 CAD · 支持精密摆盘与六点涂胶闭环",
        specs: [["自由度", "7 轴"], ["负载", "4 kg"], ["MuJoCo 工艺", "精密摆盘 / 涂胶轨迹"], ["网格", "原厂 CAD"]],
      },
    ],
  },
];
export const EQUIPMENT = EQUIPMENT_GROUPS.flatMap((g) => g.items);
