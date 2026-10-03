#include "rclcpp/rclcpp.hpp"
#include "bluesea2/srv/control.hpp"
#include "bluesea2/srv/defence_zone.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

int main(int argc, char **argv)
{
	rclcpp::init(argc, argv);
	printf("%d\n", argc);

	std::string action = (argc > 1) ? argv[1] : "";
	if ((action != "start" && action != "stop" && action != "switchZone") ||
	    (action == "switchZone" && argc != 4 && argc != 5) ||
	    ((action == "start" || action == "stop") && argc != 3 && argc != 4))
	{
		printf("usage: ros2 run bluesea2 bluesea2_node_client start  1  [node_name]     arg1 is start/stop   arg2 is num\n");
		printf("usage: ros2 run bluesea2 bluesea2_node_client switchZone  1  192.168.0.110  [node_name]     arg1 is action   arg2 is zone arg3 is ip\n");
		return 1;
	}

	// ROS 2 services are node-relative (e.g. /bluesea2_node/stop_motor);
	// the target node name is an optional last argument.
	std::string target = "bluesea2_node";
	char cmd[128] = {0};

	auto node = rclcpp::Node::make_shared("bluesea2_node_client");
	int result = 0;

	if (action == "start" || action == "stop")
	{
		if (argc == 4)
			target = argv[3];
		sprintf(cmd, "/%s/%s_motor", target.c_str(), action.c_str());
		printf("communicate service:%s\n", cmd);

		auto client = node->create_client<bluesea2::srv::Control>(cmd);
		auto request = std::make_shared<bluesea2::srv::Control::Request>();
		request->index = atoi(argv[2]);
		if (!client->wait_for_service(std::chrono::seconds(3)))
		{
			printf("Failed to find service:%s\n", cmd);
			return 1;
		}
		auto future = client->async_send_request(request);
		result = (rclcpp::spin_until_future_complete(node, future, std::chrono::seconds(5)) ==
				  rclcpp::FutureReturnCode::SUCCESS);
	}
	else // switchZone
	{
		if (argc == 5)
			target = argv[4];
		sprintf(cmd, "/%s/switchZone_motor", target.c_str());
		printf("communicate service:%s\n", cmd);

		auto client = node->create_client<bluesea2::srv::DefenceZone>(cmd);
		auto request = std::make_shared<bluesea2::srv::DefenceZone::Request>();
		request->index = atoi(argv[2]);
		request->ip = argv[3];
		if (!client->wait_for_service(std::chrono::seconds(3)))
		{
			printf("Failed to find service:%s\n", cmd);
			return 1;
		}
		auto future = client->async_send_request(request);
		result = (rclcpp::spin_until_future_complete(node, future, std::chrono::seconds(5)) ==
				  rclcpp::FutureReturnCode::SUCCESS);
	}

	if (result)
	{
		printf("OK\n");
	}
	else
	{
		printf("Failed to call service:%s\n", cmd);
		return 1;
	}

	rclcpp::shutdown();
	return 0;
}
