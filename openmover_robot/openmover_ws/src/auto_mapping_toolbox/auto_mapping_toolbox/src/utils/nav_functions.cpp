#include <utils/nav_functions.h>

bool nav_functions::initialize()
{
    node_handle_ = make_unique<ros::NodeHandle>();

    tf_buffer_ = make_unique<tf2_ros::Buffer>();
    tf_listener_ = make_unique<tf2_ros::TransformListener>(*tf_buffer_);

    try
    {
        tf_map_to_base_link_ = tf_buffer_->lookupTransform(
            LOCALIZATION_MAP,
            LOCALIZATION_BASE_LINK,
            ros::Time(0), ros::Duration(60.0));
    }
    catch (...)
    {
        cout << "no tf data from map to base_link." << endl;

        return false;
    }

    cmd_vel_mode_client_ = node_handle_->serviceClient<openmover_msgs::cmd_vel_mode_request>("cmd_vel_mode/request");
    nav_to_client_ = node_handle_->serviceClient<openmover_msgs::nav_to_request>("navigation/request");

    ros::SubscribeOptions nav_to_state_sub_opt =
        ros::SubscribeOptions::create<openmover_msgs::nav_to_state>(
            "navigation/state",
            2,
            boost::bind(&nav_functions::nav_to_state_callback, this, _1),
            ros::VoidPtr(),
            &nav_to_state_queue_);

    nav_to_state_sub_ = node_handle_->subscribe(nav_to_state_sub_opt);

    boost::thread nav_to_state_thread(boost::bind(&nav_functions::thread_loop, this));

    return true;
}

bool nav_functions::set_cmd_vel_mode(const bool &manual)
{
    bool ret = false;

    openmover_msgs::cmd_vel_mode_request cmd_vel_mode;

    cmd_vel_mode.request.manual = manual;

    if (cmd_vel_mode_client_.waitForExistence())
    {
        ret = cmd_vel_mode_client_.call(cmd_vel_mode);

        if (ret)
        {
            ret = cmd_vel_mode.response.result == CMD_RESPONSE_OK;
        }
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

    openmover_msgs::nav_to_request request;

    if (nav_to_client_.waitForExistence(ros::Duration(10.0)))
    {
        request.request.cmd = NAV_CMD_NAV_TO;
        request.request.localization_sources = string(LOCALIZATION_MAP) + string(LOCALIZATION_ODOM);
        request.request.pose.position.x = x;
        request.request.pose.position.y = y;
        request.request.pose.orientation = tf::createQuaternionMsgFromYaw(
            angles::from_degrees(yaw));
        request.request.twist.linear.x = vxmax;
        request.request.twist.angular.z = angles::from_degrees(vyawmax);
        request.request.use_global_planner = use_global_planner;
        request.request.ignore_obstacle = ignore_obstacle;

        ros::Duration(0.2).sleep();

        ret = nav_to_client_.call(request);

        if (ret)
        {
            ret = request.response.result == CMD_RESPONSE_OK;
        }

        if (ret)
        {
            ros::Time start_time = ros::Time::now();

            ros::Duration(0.5).sleep();

            while (ros::ok())
            {
                mutex_state_.lock();

                openmover_msgs::nav_to_state current_state = nav_to_state_data_;

                mutex_state_.unlock();

                if (current_state.state != NAV_STATE_RUNNING &&
                    current_state.state != NAV_STATE_BLOCKED)
                {
                    ros::Duration(0.1).sleep();
                }
                else
                {
                    break;
                }

                if ((ros::Time::now() - start_time).toSec() > 2.0)
                {
                    break;
                }
            }

            if (!async)
            {
                while (ros::ok())
                {
                    mutex_state_.lock();

                    openmover_msgs::nav_to_state current_state = nav_to_state_data_;

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
                }
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

    openmover_msgs::nav_to_request request;

    if (nav_to_client_.waitForExistence(ros::Duration(10.0)))
    {
        request.request.cmd = NAV_CMD_MOVE;
        request.request.localization_sources = string(LOCALIZATION_MAP) + string(LOCALIZATION_ODOM);
        request.request.pose.position.x = dist;
        request.request.pose.position.z = angles::from_degrees(angle);
        request.request.pose.orientation = tf::createQuaternionMsgFromYaw(0);
        request.request.twist.linear.x = vxmax;
        request.request.twist.angular.z = angles::from_degrees(vyawmax);
        request.request.ignore_obstacle = ignore_obstacle;

        ros::Duration(0.2).sleep();

        ret = nav_to_client_.call(request);

        if (ret)
        {
            ret = request.response.result == CMD_RESPONSE_OK;
        }

        if (ret)
        {
            ros::Time start_time = ros::Time::now();

            ros::Duration(0.5).sleep();

            while (ros::ok())
            {
                mutex_state_.lock();

                openmover_msgs::nav_to_state current_state = nav_to_state_data_;

                mutex_state_.unlock();

                if (current_state.state != NAV_STATE_RUNNING &&
                    current_state.state != NAV_STATE_BLOCKED)
                {
                    ros::Duration(0.1).sleep();
                }
                else
                {
                    break;
                }

                if ((ros::Time::now() - start_time).toSec() > 2.0)
                {
                    break;
                }
            }

            if (!async)
            {
                while (ros::ok())
                {
                    mutex_state_.lock();

                    openmover_msgs::nav_to_state current_state = nav_to_state_data_;

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
                }
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

    openmover_msgs::nav_to_request request;

    if (nav_to_client_.waitForExistence(ros::Duration(10.0)))
    {
        request.request.cmd = NAV_CMD_CANCEL;
        request.request.localization_sources = string(LOCALIZATION_MAP) + string(LOCALIZATION_ODOM);
        request.request.pose.orientation = tf::createQuaternionMsgFromYaw(0);

        ret = nav_to_client_.call(request);

        if (ret)
        {
            ret = request.response.result == CMD_RESPONSE_OK;
        }
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

void nav_functions::nav_to_state_callback(const openmover_msgs::nav_to_state::ConstPtr &msg)
{
    lock_guard<mutex> lock(mutex_state_);

    nav_to_state_data_ = *msg;

    nav_to_state_received_ = true;
}

void nav_functions::thread_loop()
{
    double duration = 0.02;

    while (ros::ok())
    {
        nav_to_state_queue_.callAvailable(ros::WallDuration(duration));
    }

    return;
}