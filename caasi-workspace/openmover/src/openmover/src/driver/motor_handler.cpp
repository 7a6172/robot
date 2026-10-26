// ROS 2 port of the ROS 1 motor_handler node.
// Structure and comments intentionally kept close to the original for comparability.

#include <rclcpp/rclcpp.hpp>
#include <tf2/utils.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>

#include <cmath>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <thread>

#include <unistd.h>
#include <sys/socket.h>
#include <arpa/inet.h>

#include <angles/angles.h>
#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/twist_with_covariance_stamped.hpp>
#include <std_msgs/msg/bool.hpp>
#include <openmover_msgs/msg/motor_state.hpp>
#include <openmover_msgs/srv/stop_request.hpp>
#include <openmover_msgs/srv/cmd_vel_mode_request.hpp>
#include <common/common_state_code.h>
#include <localization/localization_sources.h>
#include <navigation/navigation_state_code.h>
#include <driver/utils/crc8_maxim.h>

#define NODE_NAME "motor_handler"
#define TAG "机器人电机驱动"

using namespace std;

// 通讯定义
#define STATE_CONTROL_LEFT_MOTOR 0
#define STATE_CONTROL_RIGHT_MOTOR 1
#define MOTOR_LEFT_ID 1
#define MOTOR_RIGHT_ID 2
#define MOTOR_CMD_BUFFER_SIZE 10
#define MOTOR_RECV_BUFFER_SIZE 10

// 定义参数
// 控制频率
float control_freq = 100;

// 连接参数
string ip_address;
int port;

// 电机参数
int wheel_max_speed_rpm = 300;
int wheel_acc = 1000;

// 底盘参数
double chassis_radius = 0;
double wheel_radius = 0;
double odom_compensation_ratio = 1;

// 定义UDP
int sock = 0;
struct sockaddr_in serv_addr;

// 定义通讯相关
uint8_t comm_state = STATE_CONTROL_LEFT_MOTOR;
uint8_t packet_receive_buffer[MOTOR_RECV_BUFFER_SIZE] = {0x00};
uint8_t packet_send_buffer[MOTOR_CMD_BUFFER_SIZE] = {0x00};

// 定义电机数据结构
struct motor_speed_cmd_data_t
{
    int16_t speed_rpm_left;
    int16_t speed_rpm_right;
} motor_speed_cmd_data;

struct motor_data_t
{
    builtin_interfaces::msg::Time header_stamp;
    float phase_current_left;
    float phase_current_right;
    int16_t speed_rpm_left;
    int16_t speed_rpm_right;
    float position_deg_left;
    float position_deg_right;
    uint8_t error_code_left;
    uint8_t error_code_right;
} motor_data, last_motor_data;

// 定义航迹推算数据
struct odom_data_t
{
    double x;
    double y;
    double yaw;
    double vx;
    double vyaw;
} odom_data_raw;

geometry_msgs::msg::PoseWithCovarianceStamped odom_data;
geometry_msgs::msg::TwistWithCovarianceStamped twist_data;
openmover_msgs::msg::MotorState motor_left_state_data;
openmover_msgs::msg::MotorState motor_right_state_data;

// 定义紧急停车标志
bool emergency_from_topic = false;
bool emergency_from_srv = false;
bool emergency_flag = false;

// 定义手动控制标志
bool manual_control_flag = true;

// Actuation permission (M1, Phase 8).
//
// Defaults to DENIED and is only ever set from the `motor.actuation_enabled`
// parameter, which is declared WITHOUT a default so a missing key fails closed.
//
// This is deliberately a separate fact from "which hardware am I on": selecting a
// hardware profile must never grant permission to drive motors. It is also
// separate from the emergency and manual/auto gates below -- this flag can only
// ever deny more, never less.
//
// Enforcement happens at the single final transmission boundary in main(), where
// a nonzero speed is overwritten with zero on every iteration. That placement is
// what guarantees a command received while disabled cannot later be released when
// permission is granted.
bool actuation_enabled = false;

// Set once a speed command has arrived *after* permission was granted. Before
// that, every transmitted frame carries zero, so granting permission cannot
// release a value that was stored while disabled.
bool fresh_command_after_enable = false;

// Latch of the previous permission state, used to re-arm fresh_command_after_enable
// on every transition from disabled -> enabled.
bool actuation_was_enabled = false;

// Second, independent actuation factor: the process environment (M1 hardening).
//
// The parameter alone was not enough. A ROS 2 parameter *file* is merged into the
// same override map as a `-p` argument, and the node cannot tell where a value came
// from -- so a YAML file declaring `actuation_enabled: true` could grant actuation.
// Environment variables are not settable from a parameter file, so requiring
// `CAASI_MOTOR_ACTUATION=1` closes that bypass mechanically.
//
// Only the exact string "1" satisfies this condition. Missing, empty, "0", "true",
// "yes" and every other value deny.
bool actuation_env_ok = false;

// Name of the environment variable. Not sensitive: a permission flag, not a secret.
// Its value is never logged -- only whether the condition was satisfied.
constexpr const char *ACTUATION_ENV_VAR = "CAASI_MOTOR_ACTUATION";

// Single source of truth for "may this process drive motors at all". Both factors
// are read once at startup and never re-read, so no runtime parameter change can
// escalate permission.
inline bool actuation_permitted()
{
    return actuation_enabled && actuation_env_ok;
}

// Command watchdog (Batch D). Deliberately separate from actuation permission:
//   - permission answers "may this process drive motors at all?"
//   - the watchdog answers "should the last command still be in effect?"
// Both trees previously kept the last commanded speed forever, so a command source
// that stopped mid-command left the robot driving. This expires the command instead.
double cmd_vel_timeout = 0.5;            // seconds; <= 0 disables expiry
rclcpp::Time last_cmd_vel_stamp(0, 0, RCL_ROS_TIME);
bool cmd_vel_ever_received = false;


// 定义电机就绪标志
bool motor_ready = false;

// 节点指针
rclcpp::Node *node = nullptr;

// 定义发布器
rclcpp::Publisher<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr odom_pub;
rclcpp::Publisher<geometry_msgs::msg::TwistWithCovarianceStamped>::SharedPtr twist_pub;
rclcpp::Publisher<openmover_msgs::msg::MotorState>::SharedPtr motor_left_state_pub;
rclcpp::Publisher<openmover_msgs::msg::MotorState>::SharedPtr motor_right_state_pub;

// 定义接收器
rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_sub;
rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_manual_sub;
rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr emergency_sub;

// 定义服务器
rclcpp::Service<openmover_msgs::srv::StopRequest>::SharedPtr emergency_server;
rclcpp::Service<openmover_msgs::srv::CmdVelModeRequest>::SharedPtr manual_control_server;

// 功能函数
bool udp_init()
{
    bool ret = false;

    // 创建套接字
    if ((sock = socket(AF_INET, SOCK_DGRAM, 0)) < 0)
    {
        RCLCPP_ERROR(node->get_logger(), "%s：创建套接字失败。", TAG);

        return ret;
    }

    memset(&serv_addr, '0', sizeof(serv_addr));

    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(port);

    // 将地址从文本转换为二进制
    if (inet_pton(AF_INET, ip_address.c_str(), &serv_addr.sin_addr) <= 0)
    {
        RCLCPP_ERROR(node->get_logger(), "%s：无效地址/地址不支持。", TAG);

        return ret;
    }

    timeval tv_recv{0, 5000};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv_recv, sizeof(tv_recv));
    timeval tv_send{0, 10000};
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv_send, sizeof(tv_send));

    RCLCPP_INFO(node->get_logger(), "%s：UDP连接成功。", TAG);

    ret = true;

    return ret;
}

// 回调函数
// 速度控制回调
void cmd_vel_callback(const geometry_msgs::msg::Twist::SharedPtr msg)
{
    // M1: a command counts as "fresh" only if permission (both factors) is already
    // granted, so a value received while disabled can never authorise itself later.
    // Watchdog bookkeeping happens for every arrival, permitted or not, so the
    // staleness clock reflects reality rather than only the authorised case.
    last_cmd_vel_stamp = node->now();
    cmd_vel_ever_received = true;

    if (actuation_permitted())
    {
        fresh_command_after_enable = true;
    }
    if (!manual_control_flag)
    {
        // 解算速度
        if (emergency_flag)
        {
            motor_speed_cmd_data.speed_rpm_left = 0;
            motor_speed_cmd_data.speed_rpm_right = 0;
        }
        else
        {
            // 计算由角速度产生的线速度
            double line_speed = msg->angular.z * chassis_radius;

            // 计算车轮速度
            double speed_left = msg->linear.x - line_speed;
            double speed_right = msg->linear.x + line_speed;

            // 解算为电机 RPM
            const float rpm_scale = 60.0f / (2.0f * M_PI * wheel_radius);
            motor_speed_cmd_data.speed_rpm_left = speed_left * rpm_scale;
            motor_speed_cmd_data.speed_rpm_right = speed_right * rpm_scale;

            // 防止电机速度溢出
            motor_speed_cmd_data.speed_rpm_left =
                abs(motor_speed_cmd_data.speed_rpm_left) > wheel_max_speed_rpm ? copysign(wheel_max_speed_rpm, motor_speed_cmd_data.speed_rpm_left) : motor_speed_cmd_data.speed_rpm_left;
            motor_speed_cmd_data.speed_rpm_right =
                abs(motor_speed_cmd_data.speed_rpm_right) > wheel_max_speed_rpm ? copysign(wheel_max_speed_rpm, motor_speed_cmd_data.speed_rpm_right) : motor_speed_cmd_data.speed_rpm_right;
        }
    }
}

// 手动速度控制回调
void cmd_vel_manual_callback(const geometry_msgs::msg::Twist::SharedPtr msg)
{
    // M1: same fresh-command rule as cmd_vel_callback.
    // Watchdog bookkeeping happens for every arrival, permitted or not, so the
    // staleness clock reflects reality rather than only the authorised case.
    last_cmd_vel_stamp = node->now();
    cmd_vel_ever_received = true;

    if (actuation_permitted())
    {
        fresh_command_after_enable = true;
    }
    if (manual_control_flag)
    {
        // 解算速度
        if (emergency_flag)
        {
            motor_speed_cmd_data.speed_rpm_left = 0;
            motor_speed_cmd_data.speed_rpm_right = 0;
        }
        else
        {
            // 计算由角速度产生的线速度
            double line_speed = msg->angular.z * chassis_radius;

            // 计算车轮速度
            double speed_left = msg->linear.x - line_speed;
            double speed_right = msg->linear.x + line_speed;

            // 解算为电机 RPM
            const float rpm_scale = 60.0f / (2.0f * M_PI * wheel_radius);
            motor_speed_cmd_data.speed_rpm_left = speed_left * rpm_scale;
            motor_speed_cmd_data.speed_rpm_right = speed_right * rpm_scale;

            // 防止电机速度溢出
            motor_speed_cmd_data.speed_rpm_left =
                abs(motor_speed_cmd_data.speed_rpm_left) > wheel_max_speed_rpm ? copysign(wheel_max_speed_rpm, motor_speed_cmd_data.speed_rpm_left) : motor_speed_cmd_data.speed_rpm_left;
            motor_speed_cmd_data.speed_rpm_right =
                abs(motor_speed_cmd_data.speed_rpm_right) > wheel_max_speed_rpm ? copysign(wheel_max_speed_rpm, motor_speed_cmd_data.speed_rpm_right) : motor_speed_cmd_data.speed_rpm_right;
        }
    }
}

// 紧急制动回调
void emergency_callback(const std_msgs::msg::Bool::SharedPtr msg)
{
    emergency_from_topic = msg->data;

    emergency_flag = emergency_from_topic | emergency_from_srv;
}

void emergency_service_callback(const std::shared_ptr<rmw_request_id_t> request_header,
                                const std::shared_ptr<openmover_msgs::srv::StopRequest::Request> req,
                                std::shared_ptr<openmover_msgs::srv::StopRequest::Response> resp)
{
    (void)request_header;

    emergency_from_srv = req->enable;

    emergency_flag = emergency_from_topic | emergency_from_srv;

    resp->result = CMD_RESPONSE_OK;
}

// 手动模式回调
void cmd_vel_mode_service_callback(const std::shared_ptr<rmw_request_id_t> request_header,
                                   const std::shared_ptr<openmover_msgs::srv::CmdVelModeRequest::Request> req,
                                   std::shared_ptr<openmover_msgs::srv::CmdVelModeRequest::Response> resp)
{
    (void)request_header;

    manual_control_flag = req->manual;

    resp->result = CMD_RESPONSE_OK;
}

int main(int argc, char **argv)
{
    // 初始化ROS节点
    rclcpp::init(argc, argv);

    // 设置控制台本地化，以显示中文
    setlocale(LC_CTYPE, "zh_CN.utf8");

    // 定义ROS节点处理程序
    // The node must receive the command-line arguments, otherwise `-p key:=value`
    // overrides are not attached to it (get_parameter_overrides() would be empty and
    // parameter presence could not be verified).
    // The node must receive the command-line arguments so `--ros-args -p key:=value`
    // overrides reach it. Without this the override map is empty and the fail-closed
    // configuration check would reject every run.
    //
    // This node reads its configuration from the override map and never declares a
    // default, so allow_undeclared_parameters is left at its default (false): the
    // parameters stay undeclared, which is intentional -- declaration with a default
    // is exactly the mechanism that previously hid missing keys.
    rclcpp::NodeOptions node_options;
    node_options.arguments(std::vector<std::string>(argv + 1, argv + argc));
    node_options.allow_undeclared_parameters(true);
    node_options.automatically_declare_parameters_from_overrides(false);
    auto node_handle = rclcpp::Node::make_shared(NODE_NAME, node_options);
    node = node_handle.get();

    // 打印调试信息
    RCLCPP_INFO(node_handle->get_logger(), "%s：节点已启动。", TAG);

    // 获取参数（ROS 1: ~/motor/xxx -> ROS 2: motor.xxx）
    //
    // M1 (Phase 8): the parameters that determine physical motion are validated
    // BEFORE the socket is opened, and fail closed. The previous code used
    // declare_parameter(name, default) for every entry, which silently substitutes
    // a default when the key is missing -- measured on the real robot as
    // wheel_acc 10000 vs 1800, wheel_radius 0.0535 vs 0.05035 and
    // odom_compensation_ratio 1.0 vs 1.047. A silently wrong geometry drives a
    // robot wrongly, so "absent" is now an error rather than a fallback.
    //
    // Telemetry is unaffected: this validation runs before the publishers are
    // created, so a configuration failure stops the node instead of letting it run
    // with unverified motion parameters. That is the documented trade-off
    // (requirement 7: document rather than weaken validation).
    // ---------------------------------------------------------------------
    // M1 (Phase 8): fail-closed configuration.
    //
    // Every parameter that determines physical motion must be *supplied*. The
    // previous code used declare_parameter(name, default) throughout, which silently
    // substitutes a default when the key is missing -- measured on the real robot as
    // wheel_acc 10000 vs 1800, wheel_radius 0.0535 vs 0.05035 and
    // odom_compensation_ratio 1.0 vs 1.047. A silently wrong geometry drives a robot
    // wrongly, so absence is now a startup error.
    //
    // The override map is the correct source of truth here. It is populated before
    // anything is declared, and asking it directly keeps "supplied" and "defaulted"
    // distinguishable -- which declare_parameter(name, default) cannot do.
    //
    // Telemetry is unaffected: this runs before any publisher exists, so a bad
    // configuration stops the node rather than letting it publish from a state whose
    // motion parameters were never verified.
    // ---------------------------------------------------------------------
    {
        // Established by instrumentation on this build: the parameter overrides --
        // whatever `--ros-args -p key:=value` or a YAML file supplied -- are readable
        // here and are already present before anything is declared. get_parameter_or()
        // alone is NOT usable: it reports "not set" for an override that has not been
        // declared. Presence is therefore decided from the override map and the value
        // taken from it directly, so nothing is ever declared with a default.
        const auto &overrides =
            node_handle->get_node_parameters_interface()->get_parameter_overrides();

        std::vector<std::string> missing;
        std::vector<std::string> bad_type;

        auto has = [&](const char *key) {
            auto it = overrides.find(key);
            return it != overrides.end() &&
                   it->second.get_type() != rclcpp::ParameterType::PARAMETER_NOT_SET;
        };

        auto as_double = [&](const char *key, double &out) {
            if (!has(key)) { missing.emplace_back(key); return; }
            try { out = overrides.at(key).get<double>(); }
            catch (const std::exception &) { bad_type.emplace_back(key); }
        };
        auto as_int = [&](const char *key, int &out) {
            if (!has(key)) { missing.emplace_back(key); return; }
            try { out = (int)overrides.at(key).get<int64_t>(); }
            catch (const std::exception &) { bad_type.emplace_back(key); }
        };
        auto as_string = [&](const char *key, std::string &out) {
            if (!has(key)) { missing.emplace_back(key); return; }
            try { out = overrides.at(key).get<std::string>(); }
            catch (const std::exception &) { bad_type.emplace_back(key); }
        };
        auto as_bool = [&](const char *key, bool &out) {
            if (!has(key)) { missing.emplace_back(key); return; }
            try { out = overrides.at(key).get<bool>(); }
            catch (const std::exception &) { bad_type.emplace_back(key); }
        };

        double d_control_freq = 0.0;
        std::string s_ip;
        int i_port = 0, i_max_rpm = 0, i_acc = 0;
        double d_chassis = 0.0, d_wheel = 0.0, d_odom = 0.0;
        bool b_actuation = false;

        as_double("motor.control_freq", d_control_freq);
        as_string("motor.ip_address", s_ip);
        as_int("motor.port", i_port);
        as_int("motor.wheel_max_speed_rpm", i_max_rpm);
        as_int("motor.wheel_acc", i_acc);
        as_double("motor.chassis_radius", d_chassis);
        as_double("motor.wheel_radius", d_wheel);
        as_double("motor.odom_compensation_ratio", d_odom);
        // Actuation permission: only a supplied, literal `true` enables it.
        as_bool("motor.actuation_enabled", b_actuation);

        if (!bad_type.empty())
        {
            std::string list;
            for (const auto &b : bad_type) list += "\n  - " + b;
            RCLCPP_FATAL(node_handle->get_logger(),
                         "%s：参数类型无效，拒绝启动（不会猜测意图）。类型错误:%s",
                         TAG, list.c_str());
            rclcpp::shutdown();
            return 1;
        }

        if (!missing.empty())
        {
            std::string list;
            for (const auto &m : missing) list += "\n  - " + m;
            RCLCPP_FATAL(node_handle->get_logger(),
                         "%s：缺少必需参数，拒绝启动（不会用默认值代替）。缺失:%s",
                         TAG, list.c_str());
            rclcpp::shutdown();
            return 1;
        }

        control_freq = (float)d_control_freq;
        ip_address = s_ip;
        port = i_port;
        wheel_max_speed_rpm = i_max_rpm;
        wheel_acc = i_acc;
        chassis_radius = d_chassis;
        wheel_radius = d_wheel;
        odom_compensation_ratio = d_odom;
        actuation_enabled = b_actuation;
    }

    // Range checks: an out-of-range geometry or limit is as dangerous as a missing
    // one, so it is rejected rather than clamped silently.
    {
        std::vector<std::string> bad;
        if (!(control_freq > 0.0f && control_freq <= 1000.0f))
            bad.emplace_back("motor.control_freq must be in (0, 1000]");
        if (port <= 0 || port > 65535)
            bad.emplace_back("motor.port must be in (0, 65535]");
        if (wheel_max_speed_rpm <= 0)
            bad.emplace_back("motor.wheel_max_speed_rpm must be > 0");
        if (wheel_acc <= 0)
            bad.emplace_back("motor.wheel_acc must be > 0");
        if (!(chassis_radius > 0.0))
            bad.emplace_back("motor.chassis_radius must be > 0");
        if (!(wheel_radius > 0.0))
            bad.emplace_back("motor.wheel_radius must be > 0");
        if (!(odom_compensation_ratio > 0.0))
            bad.emplace_back("motor.odom_compensation_ratio must be > 0");
        if (ip_address.empty())
            bad.emplace_back("motor.ip_address must be non-empty");

        if (!bad.empty())
        {
            std::string list;
            for (const auto &b : bad)
            {
                list += "\n  - " + b;
            }
            RCLCPP_FATAL(node_handle->get_logger(),
                         "%s：参数取值无效，拒绝启动。问题:%s", TAG, list.c_str());
            rclcpp::shutdown();
            return 1;
        }
    }

    RCLCPP_INFO(node_handle->get_logger(),
                "%s：actuation_enabled=%s（默认禁用；非显式 true 一律禁用）",
                TAG, actuation_enabled ? "true" : "false");

    // Second factor (M1 hardening): CAASI_MOTOR_ACTUATION must be exactly "1".
    // A parameter file cannot set an environment variable, so this closes the
    // params-file bypass. Read once, here, and never re-read.
    {
        const char *env_raw = std::getenv(ACTUATION_ENV_VAR);
        actuation_env_ok = (env_raw != nullptr) && (std::strcmp(env_raw, "1") == 0);

        // Log the reason, not the value: the variable is a permission flag, and a
        // diagnostic should not encourage operators to treat it as a secret.
        if (!actuation_env_ok)
        {
            RCLCPP_WARN(node_handle->get_logger(),
                        "%s：环境条件未满足（%s 缺失或不为 \"1\"），物理驱动保持禁用。",
                        TAG, ACTUATION_ENV_VAR);
        }
    }

    // Watchdog window. Optional and defaulted on purpose: this parameter can only ever
    // reduce motion, so defaulting it is safe, unlike the motion-determining set above.
    // Read from the override map, for the same reason the required parameters are:
    // get_parameter_or() reports "not set" for an override that was never declared, so
    // it silently ignored every supplied value and always returned the default
    // (measured: 0/0.0/2.0 all reported 0.50 s). Both integer and double spellings are
    // accepted so `:=0` and `:=0.0` mean the same thing.
    {
        cmd_vel_timeout = 0.5;
        const auto &ov =
            node_handle->get_node_parameters_interface()->get_parameter_overrides();
        auto it = ov.find("motor.cmd_vel_timeout");
        if (it != ov.end())
        {
            if (it->second.get_type() == rclcpp::ParameterType::PARAMETER_DOUBLE)
                cmd_vel_timeout = it->second.get<double>();
            else if (it->second.get_type() == rclcpp::ParameterType::PARAMETER_INTEGER)
                cmd_vel_timeout = (double)it->second.get<int64_t>();
            else
                RCLCPP_WARN(node_handle->get_logger(),
                            "%s：motor.cmd_vel_timeout 类型无效，使用默认 %.2f s。",
                            TAG, cmd_vel_timeout);
        }
        if (cmd_vel_timeout < 0.0)
        {
            cmd_vel_timeout = 0.0;  // negative means "disabled", not "instant expiry"
        }
    }
    RCLCPP_INFO(node_handle->get_logger(),
                "%s：指令看门狗超时 = %.2f s%s", TAG, cmd_vel_timeout,
                cmd_vel_timeout == 0.0 ? "（已禁用）" : "");

    // One consolidated statement of the effective permission, so an operator can see
    // exactly which factor is missing without reading the code.
    if (!actuation_permitted())
    {
        const std::string missing =
            (!actuation_enabled && !actuation_env_ok) ? "参数与环境变量"
            : (!actuation_enabled)                    ? "参数 motor.actuation_enabled"
                                                      : "环境变量 CAASI_MOTOR_ACTUATION";
        RCLCPP_WARN(node_handle->get_logger(),
                    "%s：物理驱动禁用（缺少: %s）。遥测与日志照常，只发送零速度指令。",
                    TAG, missing.c_str());
    }
    else
    {
        RCLCPP_WARN(node_handle->get_logger(),
                    "%s：物理驱动已启用（参数=true 且 %s=1）。",
                    TAG, ACTUATION_ENV_VAR);
    }



    // 初始化系统
    if (udp_init())
    {
        // 初始化订阅器
        cmd_vel_sub = node_handle->create_subscription<geometry_msgs::msg::Twist>(
            "openmover/control/cmd_vel", 10, cmd_vel_callback);
        cmd_vel_manual_sub = node_handle->create_subscription<geometry_msgs::msg::Twist>(
            "openmover/control/cmd_vel_manual", 10, cmd_vel_manual_callback);
        emergency_sub = node_handle->create_subscription<std_msgs::msg::Bool>(
            "openmover/hardware/emergency", 10, emergency_callback);

        // 初始化发布器
        odom_pub = node_handle->create_publisher<geometry_msgs::msg::PoseWithCovarianceStamped>("openmover/hardware/odom", 1);
        twist_pub = node_handle->create_publisher<geometry_msgs::msg::TwistWithCovarianceStamped>("openmover/hardware/twist", 1);
        motor_left_state_pub = node_handle->create_publisher<openmover_msgs::msg::MotorState>("openmover/hardware/motor_state/left", 1);
        motor_right_state_pub = node_handle->create_publisher<openmover_msgs::msg::MotorState>("openmover/hardware/motor_state/right", 1);

        // 初始化服务器
        emergency_server = node_handle->create_service<openmover_msgs::srv::StopRequest>(
            "openmover/control/emergency/request", emergency_service_callback);
        manual_control_server = node_handle->create_service<openmover_msgs::srv::CmdVelModeRequest>(
            "openmover/control/cmd_vel_mode/request", cmd_vel_mode_service_callback);

        // 初始化数据
        odom_data.header.frame_id = LOCALIZATION_ODOM;
        tf2::Quaternion init_q;
        init_q.setRPY(0.0, 0.0, 0.0);
        odom_data.pose.pose.orientation = tf2::toMsg(init_q);
        twist_data.header.frame_id = LOCALIZATION_BASE_LINK;

        // 定义循环速度控制
        rclcpp::Rate rate(control_freq * 2);

        rclcpp::executors::SingleThreadedExecutor executor;
        executor.add_node(node_handle);

        while (rclcpp::ok())
        {
            // 处理回调函数
            executor.spin_some();

            // ------------------------------------------------------------------
            // M1 actuation boundary (Phase 8).
            //
            // This is the single place where a motor command is transmitted at
            // runtime (the other four sendto() calls are the shutdown zero-flush
            // below and are intentionally not gated). Two independent conditions
            // must hold for a nonzero speed to reach the wire:
            //
            //   1. `actuation_enabled` is explicitly true (fail-closed param), and
            //   2. a fresh command has arrived *after* permission was granted.
            //
            // Condition 2 is what prevents a command received while disabled from
            // being released later: granting permission re-arms the fresh-command
            // latch to false, so the transmitted speed stays zero until a new
            // cmd_vel actually arrives.
            //
            // The zero is applied here, after packet composition and immediately
            // before sendto(), so no path can reach the socket with a stale value.
            // ------------------------------------------------------------------
            if (actuation_permitted() && !actuation_was_enabled)
            {
                fresh_command_after_enable = false;
                motor_speed_cmd_data.speed_rpm_left = 0;
                motor_speed_cmd_data.speed_rpm_right = 0;
            }
            actuation_was_enabled = actuation_permitted();

            // Watchdog: expire a command that has not been refreshed. Cumulative and
            // independent of permission, so a silent source cannot leave the last
            // commanded speed in effect indefinitely.
            if (cmd_vel_timeout > 0.0 && cmd_vel_ever_received)
            {
                const double age = (node_handle->now() - last_cmd_vel_stamp).seconds();
                if (age > cmd_vel_timeout)
                {
                    if (motor_speed_cmd_data.speed_rpm_left != 0 ||
                        motor_speed_cmd_data.speed_rpm_right != 0)
                    {
                        RCLCPP_WARN_THROTTLE(node_handle->get_logger(), *node_handle, 2000,
                                             "%s：指令超时 %.2fs，速度归零。", TAG, age);
                    }
                    motor_speed_cmd_data.speed_rpm_left = 0;
                    motor_speed_cmd_data.speed_rpm_right = 0;
                }
            }

            // 组装发送数据
            packet_send_buffer[0] = comm_state == STATE_CONTROL_LEFT_MOTOR ? MOTOR_LEFT_ID : MOTOR_RIGHT_ID;
            packet_send_buffer[1] = 0x64;

            int16_t speed_rpm = comm_state == STATE_CONTROL_LEFT_MOTOR ? motor_speed_cmd_data.speed_rpm_left : -motor_speed_cmd_data.speed_rpm_right;

            // Final boundary guard: without permission, or without a fresh command
            // since permission was granted, the transmitted speed is zero.
            if (!actuation_permitted() || !fresh_command_after_enable)
            {
                speed_rpm = 0;
            }

            packet_send_buffer[2] = (uint8_t)(speed_rpm >> 8);
            packet_send_buffer[3] = (uint8_t)(speed_rpm & 0xff);

            packet_send_buffer[4] = 0x00;
            packet_send_buffer[5] = 0x00;

            float time_per_rpm = 1.0f / wheel_acc;
            uint8_t acc_param = min<uint8_t>(255, static_cast<uint8_t>(time_per_rpm * 10000.0f + 0.5f));
            packet_send_buffer[6] = acc_param;

            packet_send_buffer[7] = 0x00;

            if (comm_state == STATE_CONTROL_LEFT_MOTOR)
            {
                if (motor_speed_cmd_data.speed_rpm_left == 0 &&
                    (emergency_flag || abs(motor_data.speed_rpm_left) < 5))
                {
                    packet_send_buffer[7] = 0xff;
                }
            }
            else
            {
                if (motor_speed_cmd_data.speed_rpm_right == 0 &&
                    (emergency_flag || abs(motor_data.speed_rpm_right) < 5))
                {
                    packet_send_buffer[7] = 0xff;
                }
            }

            packet_send_buffer[8] = 0;

            packet_send_buffer[MOTOR_CMD_BUFFER_SIZE - 1] = crc8_maxim(packet_send_buffer, MOTOR_CMD_BUFFER_SIZE - 1);

            // 发送数据
            bool udp_error = false;

            // 发送数据
            udp_error |= (sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
                                 (struct sockaddr *)&serv_addr, sizeof(serv_addr)) == -1);

            // 等待回收数据
            ssize_t total_recv_len = 0;

            if (!udp_error)
            {
                double start_time = node_handle->now().seconds();

                do
                {
                    socklen_t addr_len = sizeof(serv_addr);
                    ssize_t recv_len = recvfrom(sock, packet_receive_buffer + total_recv_len, MOTOR_RECV_BUFFER_SIZE - total_recv_len, 0,
                                                (struct sockaddr *)&serv_addr, &addr_len);

                    if (recv_len > 0)
                    {
                        total_recv_len += recv_len;
                    }
                } while (total_recv_len < MOTOR_RECV_BUFFER_SIZE && abs(node_handle->now().seconds() - start_time) < 0.01);
            }

            if (udp_error)
            {
                RCLCPP_ERROR(node_handle->get_logger(), "%s：UDP连接失败，准备重新连接。", TAG);

                // 尝试重连
                udp_init();
            }
            else if (total_recv_len == MOTOR_RECV_BUFFER_SIZE)
            {
                motor_data.header_stamp = node_handle->now();

                if (crc8_maxim(packet_receive_buffer, MOTOR_RECV_BUFFER_SIZE - 1) == packet_receive_buffer[MOTOR_RECV_BUFFER_SIZE - 1])
                {
                    int16_t phase_current_recv = ((int16_t)packet_receive_buffer[2] << 8) | packet_receive_buffer[3];
                    int16_t speed_rpm_recv = ((int16_t)packet_receive_buffer[4] << 8) | packet_receive_buffer[5];
                    uint16_t position_deg_recv = ((uint16_t)packet_receive_buffer[6] << 8) | packet_receive_buffer[7];
                    uint8_t error_code_recv = packet_receive_buffer[8];

                    if (comm_state == STATE_CONTROL_LEFT_MOTOR && packet_receive_buffer[0] == MOTOR_LEFT_ID)
                    {
                        motor_data.phase_current_left = abs(((float)phase_current_recv / 32767.0f) * 8.0f);
                        motor_data.speed_rpm_left = speed_rpm_recv;
                        motor_data.position_deg_left = (float)position_deg_recv * 360.0f / 32767.0f;
                        motor_data.error_code_left = error_code_recv;

                        // 更新控制状态
                        comm_state =
                            (comm_state == STATE_CONTROL_LEFT_MOTOR) ? STATE_CONTROL_RIGHT_MOTOR : STATE_CONTROL_LEFT_MOTOR;
                    }
                    else if (comm_state == STATE_CONTROL_RIGHT_MOTOR && packet_receive_buffer[0] == MOTOR_RIGHT_ID)
                    {
                        motor_data.phase_current_right = abs(((float)phase_current_recv / 32767.0f) * 8.0f);
                        motor_data.speed_rpm_right = -speed_rpm_recv;
                        motor_data.position_deg_right = 360.0f - ((float)position_deg_recv * 360.0f / 32767.0f);
                        motor_data.error_code_right = error_code_recv;

                        // 右电机已获取，则说明可以更新发布数据
                        if (!motor_ready)
                        {
                            last_motor_data = motor_data;

                            motor_ready = true;
                        }
                        else
                        {
                            // 更新电机状态
                            motor_left_state_data.header.stamp = motor_data.header_stamp;
                            motor_right_state_data.header = motor_left_state_data.header;

                            motor_left_state_data.phase_current = motor_data.phase_current_left;
                            motor_left_state_data.rpm = motor_data.speed_rpm_left;
                            motor_left_state_data.position_deg = motor_data.position_deg_left;

                            motor_right_state_data.phase_current = motor_data.phase_current_right;
                            motor_right_state_data.rpm = motor_data.speed_rpm_right;
                            motor_right_state_data.position_deg = motor_data.position_deg_right;

                            motor_left_state_data.over_temperature_fault = (motor_data.error_code_left & (1 << 4)) != 0;
                            motor_left_state_data.stall_fault = (motor_data.error_code_left & (1 << 3)) != 0;
                            motor_left_state_data.phase_overcurrent_fault = (motor_data.error_code_left & (1 << 2)) != 0;
                            motor_left_state_data.overcurrent_fault = (motor_data.error_code_left & (1 << 1)) != 0;
                            motor_left_state_data.sensor_fault = (motor_data.error_code_left & (1 << 0)) != 0;

                            motor_right_state_data.over_temperature_fault = (motor_data.error_code_right & (1 << 4)) != 0;
                            motor_right_state_data.stall_fault = (motor_data.error_code_right & (1 << 3)) != 0;
                            motor_right_state_data.phase_overcurrent_fault = (motor_data.error_code_right & (1 << 2)) != 0;
                            motor_right_state_data.overcurrent_fault = (motor_data.error_code_right & (1 << 1)) != 0;
                            motor_right_state_data.sensor_fault = (motor_data.error_code_right & (1 << 0)) != 0;

                            // 计算里程
                            double dl = -(motor_data.position_deg_left - last_motor_data.position_deg_left) * M_PI / 180.0 * wheel_radius;
                            double dr = -(motor_data.position_deg_right - last_motor_data.position_deg_right) * M_PI / 180.0 * wheel_radius;
                            dl *= odom_compensation_ratio;
                            dr *= odom_compensation_ratio;

                            // 角度跳变处理
                            int loop_dl = 0;
                            while (dl > M_PI * wheel_radius && loop_dl++ < 5)
                                dl -= 2 * M_PI * wheel_radius;
                            loop_dl = 0;
                            while (dl < -M_PI * wheel_radius && loop_dl++ < 5)
                                dl += 2 * M_PI * wheel_radius;
                            int loop_dr = 0;
                            while (dr > M_PI * wheel_radius && loop_dr++ < 5)
                                dr -= 2 * M_PI * wheel_radius;
                            loop_dr = 0;
                            while (dr < -M_PI * wheel_radius && loop_dr++ < 5)
                                dr += 2 * M_PI * wheel_radius;

                            double dc = (dl + dr) / 2.0;
                            double dyaw = (dr - dl) / (2.0 * chassis_radius);

                            float sin_yaw, cos_yaw;
                            sincosf(odom_data_raw.yaw + dyaw * 0.5f, &sin_yaw, &cos_yaw);
                            odom_data_raw.x += dc * cos_yaw;
                            odom_data_raw.y += dc * sin_yaw;
                            odom_data_raw.yaw = angles::normalize_angle(odom_data_raw.yaw + dyaw);

                            // 计算速度
                            double vl = (motor_data.speed_rpm_left / 60.0) * 2.0 * M_PI * wheel_radius;
                            double vr = (motor_data.speed_rpm_right / 60.0) * 2.0 * M_PI * wheel_radius;
                            vl *= odom_compensation_ratio;
                            vr *= odom_compensation_ratio;

                            odom_data_raw.vx = (vl + vr) / 2.0;
                            odom_data_raw.vyaw = (vr - vl) / (2.0 * chassis_radius);

                            // 更新里程计
                            odom_data.header.stamp = motor_data.header_stamp;
                            twist_data.header.stamp = motor_data.header_stamp;

                            odom_data.pose.pose.position.x = odom_data_raw.x;
                            odom_data.pose.pose.position.y = odom_data_raw.y;

                            tf2::Quaternion yaw_q;
                            yaw_q.setRPY(0.0, 0.0, odom_data_raw.yaw);
                            odom_data.pose.pose.orientation = tf2::toMsg(yaw_q);

                            twist_data.twist.twist.linear.x = odom_data_raw.vx;
                            twist_data.twist.twist.angular.z = odom_data_raw.vyaw;

                            motor_left_state_pub->publish(motor_left_state_data);
                            motor_right_state_pub->publish(motor_right_state_data);

                            odom_pub->publish(odom_data);
                            twist_pub->publish(twist_data);

                            last_motor_data = motor_data;
                        }

                        // 更新控制状态
                        comm_state =
                            (comm_state == STATE_CONTROL_LEFT_MOTOR) ? STATE_CONTROL_RIGHT_MOTOR : STATE_CONTROL_LEFT_MOTOR;
                    }
                }
            }

            // 循环频率控制
            rate.sleep();
        }

        // 速度归零
        packet_send_buffer[1] = 0x64;
        packet_send_buffer[2] = 0x00;
        packet_send_buffer[3] = 0x00;
        packet_send_buffer[4] = 0x00;
        packet_send_buffer[5] = 0x00;
        packet_send_buffer[6] = 0x00;
        packet_send_buffer[7] = 0x00;
        packet_send_buffer[8] = 0x00;

        packet_send_buffer[0] = MOTOR_LEFT_ID;
        packet_send_buffer[MOTOR_CMD_BUFFER_SIZE - 1] = crc8_maxim(packet_send_buffer, MOTOR_CMD_BUFFER_SIZE - 1);
        sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        this_thread::sleep_for(chrono::milliseconds(20));
        sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        this_thread::sleep_for(chrono::milliseconds(20));

        packet_send_buffer[0] = MOTOR_RIGHT_ID;
        packet_send_buffer[MOTOR_CMD_BUFFER_SIZE - 1] = crc8_maxim(packet_send_buffer, MOTOR_CMD_BUFFER_SIZE - 1);
        sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
        this_thread::sleep_for(chrono::milliseconds(20));
        sendto(sock, packet_send_buffer, MOTOR_CMD_BUFFER_SIZE, 0,
               (struct sockaddr *)&serv_addr, sizeof(serv_addr));
    }

    rclcpp::shutdown();

    return 0;
}
