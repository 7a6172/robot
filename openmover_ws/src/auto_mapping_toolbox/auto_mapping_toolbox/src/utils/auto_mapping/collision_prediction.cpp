#include <utils/auto_mapping/collision_prediction.h>
#include <utils/topic_utils.h>

namespace collision_prediction
{
    collision_predictor::collision_predictor(const bool &use_external_dist_table, const int &free_threshold, const int &occupied_threshold)
        : use_external_dist_table_(use_external_dist_table), free_threshold_(free_threshold), occupied_threshold_(occupied_threshold - 5)
    {
        return;
    }

    void collision_predictor::initialize(rclcpp::Node::SharedPtr node)
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
        }

        if (!use_external_dist_table_)
        {
            try
            {
                auto grid = topic_utils::wait_for_message<nav_msgs::msg::OccupancyGrid>(
                    node_.get(), "map", std::chrono::duration<double>(60.0));

                if (grid != NULL)
                {
                    map_data_ = *grid;
                }
            }
            catch (...)
            {
                cout << "could not get global map." << endl;

                return;
            }

            min_dist_to_obs_table_ = calc_min_dist_to_obs_table(map_data_, occupied_threshold_);

            map_callback_group_ = node_->create_callback_group(
                rclcpp::CallbackGroupType::MutuallyExclusive, false);

            rclcpp::SubscriptionOptions map_sub_opt;
            map_sub_opt.callback_group = map_callback_group_;

            map_sub_ = node_->create_subscription<nav_msgs::msg::OccupancyGrid>(
                "map",
                2,
                [this](const nav_msgs::msg::OccupancyGrid::ConstSharedPtr msg)
                {
                    this->map_callback(msg);
                },
                map_sub_opt);

            map_executor_ = make_unique<rclcpp::executors::SingleThreadedExecutor>();
            map_executor_->add_callback_group(map_callback_group_, node_->get_node_base_interface());

            map_thread_ = thread(&collision_predictor::thread_loop, this);

            cout << "collision predictor started." << endl;
        }
        else
        {
            cout << "collision predictor started with external distance table." << endl;
        }
    }

    bool collision_predictor::check(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &p1, const int &step,
                                    const float &min_dist_to_obs, const nav_msgs::msg::OccupancyGrid &grid,
                                    const vector<float> &obs_dist_table,
                                    const int &free_threshold, const int &occupied_threshold)
    {
        exploration_segment_type ret = exploration_check_segment_type(
            p0, p1, step, min_dist_to_obs, grid, obs_dist_table, true,
            free_threshold, occupied_threshold);

        return ret == exploration_segment_type::WITH_COLLISION;
    }

    bool collision_predictor::check(const geometry_msgs::msg::PoseStamped &p0, const geometry_msgs::msg::PoseStamped &p1, const int &step,
                                    const float &min_dist_to_obs, const nav_msgs::msg::OccupancyGrid &grid,
                                    const vector<float> &obs_dist_table,
                                    const int &free_threshold, const int &occupied_threshold)
    {
        geometry_msgs::msg::Point32 pp0, pp1;
        pp0.x = p0.pose.position.x;
        pp0.y = p0.pose.position.y;
        pp0.z = p0.pose.position.z;
        pp1.x = p1.pose.position.x;
        pp1.y = p1.pose.position.y;
        pp1.z = p1.pose.position.z;

        return check(pp0, pp1, step, min_dist_to_obs, grid, obs_dist_table, free_threshold, occupied_threshold);
    }

    bool collision_predictor::check(const geometry_msgs::msg::Point32 &p0, const geometry_msgs::msg::Point32 &p1, const int &step,
                                    const float &min_dist_to_obs)
    {
        min_dist_to_obs_ = min_dist_to_obs;

        mutex_data_.lock();

        nav_msgs::msg::OccupancyGrid map_data = map_data_;
        vector<float> min_dist_to_obs_table = min_dist_to_obs_table_;

        mutex_data_.unlock();

        return check(p0, p1, step, min_dist_to_obs_,
                     map_data, min_dist_to_obs_table,
                     free_threshold_, occupied_threshold_);
    }

    bool collision_predictor::check(const geometry_msgs::msg::PoseStamped &p0, const geometry_msgs::msg::PoseStamped &p1, const int &step,
                                    const float &min_dist_to_obs)
    {
        geometry_msgs::msg::Point32 pp0, pp1;
        pp0.x = p0.pose.position.x;
        pp0.y = p0.pose.position.y;
        pp0.z = p0.pose.position.z;
        pp1.x = p1.pose.position.x;
        pp1.y = p1.pose.position.y;
        pp1.z = p1.pose.position.z;

        return check(pp0, pp1, step, min_dist_to_obs);
    }

    void collision_predictor::map_callback(const nav_msgs::msg::OccupancyGrid::ConstSharedPtr &msg)
    {
        nav_msgs::msg::OccupancyGrid map_data = *msg;
        vector<float> min_dist_to_obs_table;

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
        }

        geometry_msgs::msg::Point32 robot_position;
        robot_position.x = tf_map_to_base_link_.transform.translation.x;
        robot_position.y = tf_map_to_base_link_.transform.translation.y;

        min_dist_to_obs_table = calc_min_dist_to_obs_table(
            clear_footprint_on_grid(map_data, robot_position, min_dist_to_obs_), occupied_threshold_);

        lock_guard<mutex> lock(mutex_data_);

        map_data_ = map_data;
        min_dist_to_obs_table_ = min_dist_to_obs_table;
    }

    void collision_predictor::thread_loop()
    {
        while (rclcpp::ok() && !stop_flag_)
        {
            map_executor_->spin_once(chrono::milliseconds(20));
        }
    }
}