#include <utils/nav_functions.h>
#include <utils/topic_utils.h>
#include <tf2/LinearMath/Quaternion.h>

bool nav_functions::initialize(rclcpp::Node::SharedPtr node)
{
    node_ = node;

    tf_buffer_ = make_unique<tf2_ros::Buffer>(node_->get_clock());
    tf_listener_ = make_unique<tf2_ros::TransformListener>(*tf_buffer_, node_, true);

    try
    {
        tf_map_to_base_link_ = tf_buffer_->lookupTransform(
            LOCALIZATION_MAP,
            LOCALIZATION_BASE_LINK,
            tf2::TimePointZero, tf2::durationFromSec(60.0));
    }
    catch (...)
    {
        cout << "no tf data from map to base_link." << endl;

        return false;
    }

    nav_to_state_callback_group_ = node_->create_callback_group(
        rclcpp::CallbackGroupType::MutuallyExclusive, false);

    rclcpp::SubscriptionOptions nav_to_state_sub_opt;
    nav_to_state_sub_opt.callback_group = nav_to_state_callback_group_;

    nav_to_state_sub_ = node_->create_subscription<openmover_msgs::msg::NavToState>(
        "navigation/state",
        2,
        [this](const openmover_msgs::msg::NavToState::ConstSharedPtr msg)
        {
            this->nav_to_state_callback(msg);
        },
        nav_to_state_sub_opt);

    nav_to_state_executor_ = make_unique<rclcpp::executors::SingleThreadedExecutor>();
    nav_to_state_executor_->add_callback_group(
        nav_to_state_callback_group_, node_->get_node_base_interface());

    nav_to_state_thread_ = make_unique<thread>(&nav_functions::thread_loop, this);

    return true;
}

bool nav_functions::set_cmd_vel_mode(const bool &manual)
{
    bool ret = false;

    auto cmd_vel_mode = make_shared<openmover_msgs::srv::CmdVelModeRequest::Request>();

    cmd_vel_mode->manual = manual;

    auto response = topic_utils::call_service<openmover_msgs::srv::CmdVelModeRequest>(
        node_.get(), "cmd_vel_mode/request", cmd_vel_mode, std::chrono::duration<double>(60.0));

    if (response != nullptr)
    {
        ret = response->result == CMD_RESPONSE_OK;
    }

    return ret;
}

bool nav_functions::nav_to(const float &x, const float &y, const float &yaw,
                           const float &vxmax, const float &vyawmax,
                           const bool &use_global_planner,
                           const bool &ignore_obstacle,
                           const bool &async)
{
    bool ret = false;

    set_cmd_vel_mode(false);

    auto request = make_shared<openmover_msgs::srv::NavToRequest::Request>();

    request->cmd = NAV_CMD_NAV_TO;
    request->localization_sources = string(LOCALIZATION_MAP) + string(LOCALIZATION_ODOM);
    request->pose.position.x = x;
    request->pose.position.y = y;
    request->pose.orientation = tf2::toMsg(tf2::Quaternion(tf2::Vector3(0.0, 0.0, 1.0),
                                                           angles::from_degrees(yaw)));
    request->twist.linear.x = vxmax;
    request->twist.angular.z = angles::from_degrees(vyawmax);
    request->use_global_planner = use_global_planner;
    request->ignore_obstacle = ignore_obstacle;

    this_thread::sleep_for(chrono::milliseconds(200));

    auto response = topic_utils::call_service<openmover_msgs::srv::NavToRequest>(
        node_.get(), "navigation/request", request, std::chrono::duration<double>(10.0));

    if (response != nullptr)
    {
        ret = response->result == CMD_RESPONSE_OK;
    }

    if (ret)
    {
        rclcpp::Time start_time = node_->now();

        this_thread::sleep_for(chrono::milliseconds(500));

        while (rclcpp::ok())
        {
            mutex_state_.lock();

            openmover_msgs::msg::NavToState current_state = nav_to_state_data_;

            mutex_state_.unlock();

            if (current_state.state != NAV_STATE_RUNNING &&
                current_state.state != NAV_STATE_BLOCKED)
            {
                this_thread::sleep_for(chrono::milliseconds(100));
            }
            else
            {
                break;
            }

            if ((node_->now() - start_time).seconds() > 2.0)
            {
                break;
            }
        }

        if (!async)
        {
            while (rclcpp::ok())
            {
                mutex_state_.lock();

                openmover_msgs::msg::NavToState current_state = nav_to_state_data_;

                mutex_state_.unlock();

                if (current_state.state == NAV_STATE_REACHED)
                {
                    ret = true;

                    break;
                }

                if (current_state.state == NAV_STATE_ERROR)
                {
                    ret = false;

                    break;
                }

                this_thread::sleep_for(chrono::milliseconds(10));
            }
        }
    }

    if (!async)
    {
        set_cmd_vel_mode(true);
    }

    return ret;
}

bool nav_functions::move(const float &dist, const float &angle,
                         const float &vxmax, const float &vyawmax,
                         const bool &ignore_obstacle,
                         const bool &async)
{
    bool ret = false;

    set_cmd_vel_mode(false);

    auto request = make_shared<openmover_msgs::srv::NavToRequest::Request>();

    request->cmd = NAV_CMD_MOVE;
    request->localization_sources = string(LOCALIZATION_MAP) + string(LOCALIZATION_ODOM);
    request->pose.position.x = dist;
    request->pose.position.z = angles::from_degrees(angle);
    request->pose.orientation = tf2::toMsg(tf2::Quaternion(tf2::Vector3(0.0, 0.0, 1.0), 0.0));
    request->twist.linear.x = vxmax;
    request->twist.angular.z = angles::from_degrees(vyawmax);
    request->ignore_obstacle = ignore_obstacle;

    this_thread::sleep_for(chrono::milliseconds(200));

    auto response = topic_utils::call_service<openmover_msgs::srv::NavToRequest>(
        node_.get(), "navigation/request", request, std::chrono::duration<double>(10.0));

    if (response != nullptr)
    {
        ret = response->result == CMD_RESPONSE_OK;
    }

    if (ret)
    {
        rclcpp::Time start_time = node_->now();

        this_thread::sleep_for(chrono::milliseconds(500));

        while (rclcpp::ok())
        {
            mutex_state_.lock();

            openmover_msgs::msg::NavToState current_state = nav_to_state_data_;

            mutex_state_.unlock();

            if (current_state.state != NAV_STATE_RUNNING &&
                current_state.state != NAV_STATE_BLOCKED)
            {
                this_thread::sleep_for(chrono::milliseconds(100));
            }
            else
            {
                break;
            }

            if ((node_->now() - start_time).seconds() > 2.0)
            {
                break;
            }
        }

        if (!async)
        {
            while (rclcpp::ok())
            {
                mutex_state_.lock();

                openmover_msgs::msg::NavToState current_state = nav_to_state_data_;

                mutex_state_.unlock();

                if (current_state.state == NAV_STATE_REACHED)
                {
                    ret = true;

                    break;
                }

                if (current_state.state == NAV_STATE_ERROR)
                {
                    ret = false;

                    break;
                }

                this_thread::sleep_for(chrono::milliseconds(10));
            }
        }
    }

    if (!async)
    {
        set_cmd_vel_mode(true);
    }

    return ret;
}

bool nav_functions::cancel()
{
    bool ret = false;

    auto request = make_shared<openmover_msgs::srv::NavToRequest::Request>();

    request->cmd = NAV_CMD_CANCEL;
    request->localization_sources = string(LOCALIZATION_MAP) + string(LOCALIZATION_ODOM);
    request->pose.orientation = tf2::toMsg(tf2::Quaternion(tf2::Vector3(0.0, 0.0, 1.0), 0.0));

    auto response = topic_utils::call_service<openmover_msgs::srv::NavToRequest>(
        node_.get(), "navigation/request", request, std::chrono::duration<double>(10.0));

    if (response != nullptr)
    {
        ret = response->result == CMD_RESPONSE_OK;
    }

    if (ret)
    {
        set_cmd_vel_mode(true);
    }

    return ret;
}

string nav_functions::get_nav_state()
{
    lock_guard<mutex> lock(mutex_state_);

    return nav_to_state_data_.state;
}

void nav_functions::nav_to_state_callback(const openmover_msgs::msg::NavToState::ConstSharedPtr &msg)
{
    lock_guard<mutex> lock(mutex_state_);

    nav_to_state_data_ = *msg;

    nav_to_state_received_ = true;
}

void nav_functions::thread_loop()
{
    while (rclcpp::ok())
    {
        nav_to_state_executor_->spin_once(chrono::milliseconds(20));
    }

    return;
}
