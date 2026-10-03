#ifndef TOPIC_UTILS_H
#define TOPIC_UTILS_H

#include <chrono>
#include <string>

#include "rclcpp/rclcpp.hpp"

namespace topic_utils
{
    // One-shot subscription helper mirroring ros::topic::waitForMessage<T>(topic, timeout).
    // Subscribes with the given QoS, spins (on a dedicated executor bound to a dedicated
    // callback group) until one message is received or the timeout elapses.
    // Returns nullptr when no message was received in time.
    template <class T>
    typename T::SharedPtr wait_for_message(rclcpp::Node *node,
                                           const std::string &topic,
                                           const rclcpp::QoS &qos,
                                           const std::chrono::duration<double> &timeout)
    {
        typename T::SharedPtr result = nullptr;

        auto callback_group = node->create_callback_group(
            rclcpp::CallbackGroupType::MutuallyExclusive, false);

        rclcpp::SubscriptionOptions subscription_options;
        subscription_options.callback_group = callback_group;

        auto subscription = node->create_subscription<T>(
            topic, qos,
            [&result](typename T::SharedPtr msg)
            {
                result = msg;
            },
            subscription_options);

        rclcpp::executors::SingleThreadedExecutor executor;
        executor.add_callback_group(callback_group, node->get_node_base_interface());

        auto start_time = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start_time);

        while (rclcpp::ok() && (result == nullptr) && (elapsed < timeout))
        {
            executor.spin_once(std::chrono::duration_cast<std::chrono::nanoseconds>(timeout - elapsed));

            elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start_time);
        }

        return result;
    }

    template <class T>
    typename T::SharedPtr wait_for_message(rclcpp::Node *node,
                                           const std::string &topic,
                                           const std::chrono::duration<double> &timeout)
    {
        return wait_for_message<T>(node, topic, rclcpp::QoS(rclcpp::KeepLast(1)).transient_local().reliable(), timeout);
    }

    // Blocking service call mirroring ros::ServiceClient::call(request) with a timeout.
    // A dedicated client is created per call (in a dedicated callback group spun by a
    // dedicated executor), which keeps concurrent calls from different threads safe and
    // mirrors the ROS 1 behavior of ad-hoc service clients created at the call sites.
    // Returns nullptr when the service is unavailable or the call times out.
    template <class SrvT>
    typename SrvT::Response::SharedPtr call_service(rclcpp::Node *node,
                                                    const std::string &service_name,
                                                    typename SrvT::Request::SharedPtr request,
                                                    const std::chrono::duration<double> &timeout)
    {
        auto callback_group = node->create_callback_group(
            rclcpp::CallbackGroupType::MutuallyExclusive, false);

        auto client = node->create_client<SrvT>(service_name, rclcpp::ServicesQoS(), callback_group);

        if (!client->wait_for_service(std::chrono::duration_cast<std::chrono::nanoseconds>(timeout)))
        {
            return nullptr;
        }

        auto future = client->async_send_request(request);

        rclcpp::executors::SingleThreadedExecutor executor;
        executor.add_callback_group(callback_group, node->get_node_base_interface());

        auto start_time = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start_time);

        while (rclcpp::ok() && (elapsed < timeout))
        {
            if (future.wait_for(std::chrono::seconds(0)) == std::future_status::ready)
            {
                return future.get();
            }

            executor.spin_once(std::chrono::duration_cast<std::chrono::nanoseconds>(timeout - elapsed));

            elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start_time);
        }

        return nullptr;
    }
}

#endif
