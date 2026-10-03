#include <utils/auto_mapping/collision_prediction.h>

namespace collision_prediction
{
    collision_predictor::collision_predictor(const bool &use_external_dist_table, const int &free_threshold, const int &occupied_threshold)
        : use_external_dist_table_(use_external_dist_table), free_threshold_(free_threshold), occupied_threshold_(occupied_threshold - 5)
    {
        return;
    }

    void collision_predictor::initialize()
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
        }

        if (!use_external_dist_table_)
        {
            try
            {
                auto grid = ros::topic::waitForMessage<nav_msgs::OccupancyGrid>("map", ros::Duration(60.0));

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

            map_sub_ = node_handle_->subscribe(
                "map",
                2,
                &collision_predictor::map_callback,
                this);

            boost::thread map_thread_(boost::bind(&collision_predictor::thread_loop, this));

            cout << "collision predictor started." << endl;
        }
        else
        {
            cout << "collision predictor started with external distance table." << endl;
        }
    }

    bool collision_predictor::check(const geometry_msgs::Point32 &p0, const geometry_msgs::Point32 &p1, const int &step,
                                    const float &min_dist_to_obs, const nav_msgs::OccupancyGrid &grid,
                                    const vector<float> &obs_dist_table,
                                    const int &free_threshold, const int &occupied_threshold)
    {
        exploration_segment_type ret = exploration_check_segment_type(
            p0, p1, step, min_dist_to_obs, grid, obs_dist_table, true,
            free_threshold, occupied_threshold);

        return ret == exploration_segment_type::WITH_COLLISION;
    }

    bool collision_predictor::check(const geometry_msgs::PoseStamped &p0, const geometry_msgs::PoseStamped &p1, const int &step,
                                    const float &min_dist_to_obs, const nav_msgs::OccupancyGrid &grid,
                                    const vector<float> &obs_dist_table,
                                    const int &free_threshold, const int &occupied_threshold)
    {
        geometry_msgs::Point32 pp0, pp1;
        pp0.x = p0.pose.position.x;
        pp0.y = p0.pose.position.y;
        pp0.z = p0.pose.position.z;
        pp1.x = p1.pose.position.x;
        pp1.y = p1.pose.position.y;
        pp1.z = p1.pose.position.z;

        return check(pp0, pp1, step, min_dist_to_obs, grid, obs_dist_table, free_threshold, occupied_threshold);
    }

    bool collision_predictor::check(const geometry_msgs::Point32 &p0, const geometry_msgs::Point32 &p1, const int &step,
                                    const float &min_dist_to_obs)
    {
        min_dist_to_obs_ = min_dist_to_obs;

        mutex_data_.lock();

        nav_msgs::OccupancyGrid map_data = map_data_;
        vector<float> min_dist_to_obs_table = min_dist_to_obs_table_;

        mutex_data_.unlock();

        return check(p0, p1, step, min_dist_to_obs_,
                     map_data, min_dist_to_obs_table,
                     free_threshold_, occupied_threshold_);
    }

    bool collision_predictor::check(const geometry_msgs::PoseStamped &p0, const geometry_msgs::PoseStamped &p1, const int &step,
                                    const float &min_dist_to_obs)
    {
        geometry_msgs::Point32 pp0, pp1;
        pp0.x = p0.pose.position.x;
        pp0.y = p0.pose.position.y;
        pp0.z = p0.pose.position.z;
        pp1.x = p1.pose.position.x;
        pp1.y = p1.pose.position.y;
        pp1.z = p1.pose.position.z;

        return check(pp0, pp1, step, min_dist_to_obs);
    }

    void collision_predictor::map_callback(const nav_msgs::OccupancyGrid::ConstPtr &msg)
    {
        nav_msgs::OccupancyGrid map_data = *msg;
        vector<float> min_dist_to_obs_table;

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
        }

        geometry_msgs::Point32 robot_position;
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
        ros::spin();
    }
}