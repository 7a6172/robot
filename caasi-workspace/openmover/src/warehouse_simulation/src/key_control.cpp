// ============================================================================
// key_control.cpp
//
// ROS 2 port of warehouse_simulation_toolkit/src/key_control.cpp
// （方向键遥控，q 退出，发布 Twist 到 cmd_vel）。
// 与 ROS 1 原版的差异（均为有意改进）：
//   1. DOWN 为倒车（原版 DOWN 映射 -0.0，只停不退）；
//   2. 按住持续发送：按住方向键期间以 20 Hz 持续发布速度指令，
//      松开约 0.6 s 内无新按键事件即自动发布一次零速停车
//      （终端只能感知“按下”、无法感知“松开”，故依赖系统按键重复
//      + 超时判断；请确保系统键盘重复已开启，桌面环境默认开启）。
//
// 映射（与原版一致）：UP→+0.7·scale_linear，DOWN→-0.7·scale_linear，
// LEFT→+0.3·scale_angular（逆时针），RIGHT→-0.3·scale_angular（顺时针）。
// ============================================================================
#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <poll.h>
#include <termios.h>
#include <unistd.h>

#include <signal.h>
#include <atomic>

using namespace std::chrono_literals;

// 方向键转义序列末字符：ESC [ A/B/C/D
#define KEYCODE_RIGHT 0x43
#define KEYCODE_LEFT  0x44
#define KEYCODE_UP    0x41
#define KEYCODE_DOWN  0x42

#define KEYCODE_Q 0x71
#define KEYCODE_ESC 0x1B
#define KEYCODE_CSI 0x5B

// 按住期间持续发布；松开后超过该时长未收到按键重复事件 → 停车
static constexpr double KEY_TIMEOUT_S = 0.6;
static constexpr double PUBLISH_RATE_HZ = 20.0;

enum class Key { NONE, UP, DOWN, LEFT, RIGHT };

std::atomic<bool> g_quit{false};
void sigHandler(int) { g_quit = true; }

int g_kfd = 0;
struct termios g_cooked, g_raw;

void kbhitRestore(int)
{
	g_quit = true;  // 走主循环的优雅退出路径：发布零速停车并恢复终端
}

struct kbhit_guard {
	kbhit_guard()
	{
		tcgetattr(g_kfd, &g_cooked);
		memcpy(&g_raw, &g_cooked, sizeof(g_raw));
		g_raw.c_lflag &= ~(ICANON | ECHO);
		g_raw.c_cc[VEOL] = 1;
		g_raw.c_cc[VEOF] = 2;
		tcsetattr(g_kfd, TCSANOW, &g_raw);
		signal(SIGINT, kbhitRestore);
	}
	~kbhit_guard() { tcsetattr(g_kfd, TCSANOW, &g_cooked); }
};

int main(int argc, char **argv)
{
	setvbuf(stdout, NULL, _IONBF, BUFSIZ);
	rclcpp::init(argc, argv);

	auto node = rclcpp::Node::make_shared("key_control");
	double l_scale = 2.0, a_scale = 2.0;
	node->declare_parameter("scale_linear", l_scale);
	node->declare_parameter("scale_angular", a_scale);
	node->get_parameter("scale_linear", l_scale);
	node->get_parameter("scale_angular", a_scale);

	auto pub = node->create_publisher<geometry_msgs::msg::Twist>("/cmd_vel", 1);
	signal(SIGINT, sigHandler);

	puts("Reading from keyboard");
	puts("---------------------------------");
	puts("Hold UP/DOWN : forward / reverse (repeats while held)");
	puts("Hold LEFT/RIGHT : rotate CCW / CW");
	puts("Release all keys : auto stop | q to quit");
	puts("---------------------------------");

	kbhit_guard term_guard;

	auto twistFor = [&](Key k) {
		geometry_msgs::msg::Twist t;
		switch (k) {
		case Key::UP:    t.linear.x =  0.7 * l_scale; break;
		case Key::DOWN:  t.linear.x = -0.7 * l_scale; break;  // ROS 1 原版无倒车，此处为改进
		case Key::LEFT:  t.angular.z =  0.3 * a_scale; break;
		case Key::RIGHT: t.angular.z = -0.3 * a_scale; break;
		default: break;
		}
		return t;
	};

	const geometry_msgs::msg::Twist zero;
	Key active = Key::NONE;
	auto last_event = std::chrono::steady_clock::now() - 10s;
	int esc_state = 0;  // 0=normal, 1=got ESC, 2=got CSI '['
	bool stdin_alive = true;

	while (rclcpp::ok() && !g_quit) {
		// ---- 非阻塞读取按键（方向键为 ESC [ A/B/C/D 三字节序列）----
		if (stdin_alive) {
			struct pollfd pfd;
			pfd.fd = STDIN_FILENO;
			pfd.events = POLLIN;
			pfd.revents = 0;
			while (poll(&pfd, 1, 0) > 0 && (pfd.revents & POLLIN)) {
				char buf[32];
				ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
				if (n <= 0) { stdin_alive = false; break; }
				for (ssize_t i = 0; i < n; ++i) {
					unsigned char c = buf[i];
					switch (esc_state) {
					case 0:
						if (c == KEYCODE_ESC) esc_state = 1;
						else if (c == KEYCODE_Q || c == 'Q') g_quit = true;
						break;
					case 1:
						esc_state = (c == KEYCODE_CSI) ? 2 : (c == KEYCODE_ESC) ? 1 : 0;
						break;
					default: // 等待方向字符
						if      (c == KEYCODE_UP)    active = Key::UP;
						else if (c == KEYCODE_DOWN)  active = Key::DOWN;
						else if (c == KEYCODE_LEFT)  active = Key::LEFT;
						else if (c == KEYCODE_RIGHT) active = Key::RIGHT;
						if (active != Key::NONE)
							last_event = std::chrono::steady_clock::now();
						esc_state = 0;
						break;
					}
				}
			}
		}

		// ---- 按住持续发布；松开（超时）后发布一次零速停车 ----
		if (active != Key::NONE) {
			double since = std::chrono::duration<double>(
				std::chrono::steady_clock::now() - last_event).count();
			if (since < KEY_TIMEOUT_S) {
				pub->publish(twistFor(active));
			} else {
				pub->publish(zero);
				active = Key::NONE;
			}
		}

		rclcpp::sleep_for(std::chrono::milliseconds(1000 / static_cast<int>(PUBLISH_RATE_HZ)));
	}

	pub->publish(zero);  // 退出前显式停车
	tcsetattr(g_kfd, TCSANOW, &g_cooked);
	rclcpp::shutdown();
	return 0;
}
