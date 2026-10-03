// ROS 2 replacement for ros::topic::waitForMessage.
// Subscribes once, polls with take() until a message arrives or the timeout
// elapses. take()-based polling needs no executor, so this helper is safe to
// call from inside service callbacks while the node is already attached to
// another executor (rclcpp forbids attaching one node to two executors).
#pragma once

#include <chrono>
#include <memory>
#include <string>
#include <thread>

#include "rclcpp/rclcpp.hpp"

namespace openmover
{

template <typename MessageT>
typename MessageT::SharedPtr wait_for_message(
    rclcpp::Node * node,
    const std::string & topic,
    const rclcpp::QoS & qos = rclcpp::QoS(1),
    const std::chrono::nanoseconds timeout = std::chrono::seconds(60))
{
  // 回调永不会被触发（不依赖任何执行器），仅用于创建订阅以接收数据
  auto subscription = node->create_subscription<MessageT>(
      topic, qos, [](typename MessageT::SharedPtr) {});

  auto start = std::chrono::steady_clock::now();

  while (rclcpp::ok())
  {
    auto msg = std::make_shared<MessageT>();
    rclcpp::MessageInfo message_info;

    if (subscription->take(*msg, message_info))
    {
      return msg;
    }

    if (timeout >= std::chrono::nanoseconds(0) &&
        (std::chrono::steady_clock::now() - start) > timeout)
    {
      break;
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }

  return nullptr;
}

}  // namespace openmover
