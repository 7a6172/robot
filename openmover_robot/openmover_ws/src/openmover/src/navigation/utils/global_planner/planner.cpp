#include <costmap_2d/cost_values.h>
#include <costmap_2d/costmap_2d.h>
#include "navigation/utils/global_planner/planner.h"
#include "navigation/utils/global_planner/dijkstra.h"
#include "navigation/utils/global_planner/grid_path.h"
#include "navigation/utils/global_planner/gradient_path.h"
#include "navigation/utils/global_planner/quadratic_calculator.h"
#include <pcl/point_cloud.h>
#include <pcl/kdtree/kdtree_flann.h>

std::vector<float> shortest_distances;
std::vector<std::pair<double, double>> shortest_distance_coordinates;
geometry_msgs::Polygon footprint_polygon;

// void compute_obstacle_shortest_distances(
//     costmap_2d::Costmap2D *costmap, float lethal_cost,
//     std::vector<float> &shortest_distances,
//     std::vector<std::pair<double, double>> &shortest_distance_coordinates,
//     nav_msgs::OccupancyGrid &grid,
//     const geometry_msgs::PoseStamped &start,
//     const geometry_msgs::PoseStamped &goal,
//     float &min_dist_to_obs)
// {
//     unsigned char *costs = costmap->getCharMap();
//     int costmap_width = costmap->getSizeInCellsX();
//     int costmap_height = costmap->getSizeInCellsY();
//     float costmap_resolution = costmap->getResolution();

//     float costmap_origin_x = costmap->getOriginX();
//     float costmap_origin_y = costmap->getOriginY();

//     pcl::PointCloud<pcl::PointXYZ>::Ptr cloud(new pcl::PointCloud<pcl::PointXYZ>);
//     map<int, bool> del_points;

//     for (int i = 0; i < costmap_width * costmap_height; ++i)
//     {
//         if (costs[i] >= lethal_cost)
//         {
//             int x = i % costmap_width;
//             int y = i / costmap_width;
//             float wx = costmap_origin_x + x * costmap_resolution;
//             float wy = costmap_origin_y + y * costmap_resolution;
//             float dist_to_start = std::sqrt(
//                 std::pow(wx - start.pose.position.x, 2) + std::pow(wy - start.pose.position.y, 2));
//             float dist_to_goal = std::sqrt(
//                 std::pow(wx - goal.pose.position.x, 2) + std::pow(wy - goal.pose.position.y, 2));

//             // if (dist_to_start > min_dist_to_obs + 0.02 &&
//             //     dist_to_goal > min_dist_to_obs + 0.02)
//             if (dist_to_start > min_dist_to_obs + 0.02)
//             {
//                 cloud->push_back(pcl::PointXYZ(
//                     costmap_origin_x + x * costmap_resolution,
//                     costmap_origin_y + y * costmap_resolution,
//                     0));
//             }
//             else
//             {
//                 del_points[i] = true;
//             }
//         }
//     }

//     if (!grid.data.empty())
//     {
//         int grid_width = grid.info.width;
//         int grid_height = grid.info.height;
//         float grid_resolution = grid.info.resolution;
//         float grid_origin_x = grid.info.origin.position.x;
//         float grid_origin_y = grid.info.origin.position.y;

//         for (int i = 0; i < grid_width * grid_height; ++i)
//         {
//             if (grid.data[i] >= lethal_cost)
//             {
//                 int x = i % grid_width;
//                 int y = i / grid_width;

//                 float map_x = grid_origin_x + x * grid_resolution;
//                 float map_y = grid_origin_y + y * grid_resolution;
//                 float dist_to_start = std::sqrt(
//                     std::pow(map_x - start.pose.position.x, 2) + std::pow(map_y - start.pose.position.y, 2));
//                 float dist_to_goal = std::sqrt(
//                     std::pow(map_x - goal.pose.position.x, 2) + std::pow(map_y - goal.pose.position.y, 2));

//                 // if (dist_to_start > min_dist_to_obs + 0.02 &&
//                 //     dist_to_goal > min_dist_to_obs + 0.02)
//                 if (dist_to_start > min_dist_to_obs + 0.02)
//                 {
//                     cloud->push_back(pcl::PointXYZ(map_x, map_y, 0));
//                 }
//             }
//         }
//     }

//     pcl::KdTreeFLANN<pcl::PointXYZ> kdtree;
//     kdtree.setInputCloud(cloud);

//     shortest_distances.resize(costmap_width * costmap_height, FLT_MAX);
//     shortest_distance_coordinates.resize(costmap_width * costmap_height, std::make_pair(0.0, 0.0));

//     pcl::PointXYZ search_point;

// #pragma omp parallel for schedule(dynamic)
//     for (int i = 0; i < costmap_width * costmap_height; ++i)
//     {
//         if (costs[i] < lethal_cost || del_points.count(i) > 0)
//         {
//             search_point.x = costmap_origin_x + (i % costmap_width) * costmap_resolution;
//             search_point.y = costmap_origin_y + (i / costmap_width) * costmap_resolution;
//             search_point.z = 0;

//             std::vector<int> pointIdxNKNSearch(1);
//             std::vector<float> pointNKNSquaredDistance(1);

//             if (kdtree.nearestKSearch(search_point, 1, pointIdxNKNSearch, pointNKNSquaredDistance) > 0)
//             {
//                 shortest_distances[i] = std::sqrt(pointNKNSquaredDistance[0]);
//                 auto &p = cloud->points[pointIdxNKNSearch[0]];

//                 float costmap_x = (p.x - costmap_origin_x) / costmap_resolution;
//                 float costmap_y = (p.y - costmap_origin_y) / costmap_resolution;

//                 shortest_distance_coordinates[i] = std::make_pair(costmap_x, costmap_y);
//             }
//         }
//         else
//         {
//             shortest_distances[i] = 0.0f;
//             shortest_distance_coordinates[i] = std::make_pair(
//                 static_cast<double>(i % costmap_width),
//                 static_cast<double>(i / costmap_width));
//         }
//     }
// }

void compute_obstacle_shortest_distances(
    costmap_2d::Costmap2D *costmap, float lethal_cost,
    std::vector<float> &shortest_distances,
    std::vector<std::pair<double, double>> &shortest_distance_coordinates,
    nav_msgs::OccupancyGrid &grid,
    const geometry_msgs::PoseStamped &start,
    const geometry_msgs::PoseStamped &goal,
    float &min_dist_to_obs)
{
    unsigned char *costs = costmap->getCharMap();
    const int c_width = costmap->getSizeInCellsX();
    const int c_height = costmap->getSizeInCellsY();
    const float c_res = costmap->getResolution();
    const float c_org_x = costmap->getOriginX();
    const float c_org_y = costmap->getOriginY();

    const size_t c_cells = static_cast<size_t>(c_width) * c_height;
    std::vector<char> del_flags(c_cells, 0);

    pcl::PointCloud<pcl::PointXYZ>::Ptr cloud(new pcl::PointCloud<pcl::PointXYZ>);
    cloud->points.reserve(c_cells / 10);

#pragma omp parallel
    {
        pcl::PointCloud<pcl::PointXYZ> cloud_local;
        cloud_local.points.reserve(1024);

#pragma omp for schedule(static) nowait
        for (long long idx = 0; idx < static_cast<long long>(c_cells); ++idx)
        {
            if (costs[idx] < lethal_cost)
            {
                continue;
            }

            int x = idx % c_width;
            int y = idx / c_width;
            float wx = c_org_x + x * c_res;
            float wy = c_org_y + y * c_res;

            float dist_to_start = std::hypot(wx - start.pose.position.x,
                                             wy - start.pose.position.y);

            if (dist_to_start > min_dist_to_obs + 0.02f)
            {
                cloud_local.emplace_back(wx, wy, 0.0f);
            }
            else
            {
                del_flags[idx] = 1;
            }
        }

#pragma omp critical
        cloud->points.insert(cloud->points.end(),
                             cloud_local.points.begin(), cloud_local.points.end());
    }

    if (!grid.data.empty())
    {
        const int g_width = grid.info.width;
        const int g_height = grid.info.height;
        const float g_res = grid.info.resolution;
        const float g_org_x = grid.info.origin.position.x;
        const float g_org_y = grid.info.origin.position.y;
        const size_t g_cells = static_cast<size_t>(g_width) * g_height;

#pragma omp parallel
        {
            pcl::PointCloud<pcl::PointXYZ> cloud_local;
            cloud_local.points.reserve(1024);

#pragma omp for schedule(static) nowait
            for (long long idx = 0; idx < static_cast<long long>(g_cells); ++idx)
            {
                if (grid.data[idx] < lethal_cost)
                {
                    continue;
                }

                int x = idx % g_width;
                int y = idx / g_width;
                float mx = g_org_x + x * g_res;
                float my = g_org_y + y * g_res;

                float dist_to_start = std::hypot(mx - start.pose.position.x,
                                                 my - start.pose.position.y);

                if (dist_to_start > min_dist_to_obs + 0.02f)
                    cloud_local.emplace_back(mx, my, 0.0f);
            }

#pragma omp critical
            cloud->points.insert(cloud->points.end(),
                                 cloud_local.points.begin(), cloud_local.points.end());
        }
    }

    pcl::KdTreeFLANN<pcl::PointXYZ> kdtree;
    kdtree.setInputCloud(cloud);

    shortest_distances.assign(c_cells, std::numeric_limits<float>::max());
    shortest_distance_coordinates.assign(
        c_cells, std::make_pair(0.0, 0.0));

#pragma omp parallel for schedule(static)
    for (long long idx = 0; idx < static_cast<long long>(c_cells); ++idx)
    {
        if (costs[idx] >= lethal_cost && !del_flags[idx])
        {
            shortest_distances[idx] = 0.0f;
            shortest_distance_coordinates[idx] =
                {static_cast<double>(idx % c_width),
                 static_cast<double>(idx / c_width)};

            continue;
        }

        pcl::PointXYZ query_pt;
        query_pt.x = c_org_x + (idx % c_width) * c_res;
        query_pt.y = c_org_y + (idx / c_width) * c_res;
        query_pt.z = 0.0f;

        std::vector<int> nn_idx(1);
        std::vector<float> nn_sqdist(1);

        if (kdtree.nearestKSearch(query_pt, 1, nn_idx, nn_sqdist) > 0)
        {
            shortest_distances[idx] = std::sqrt(nn_sqdist[0]);

            const auto &p = cloud->points[nn_idx[0]];
            float cx = (p.x - c_org_x) / c_res;
            float cy = (p.y - c_org_y) / c_res;
            shortest_distance_coordinates[idx] = {cx, cy};
        }
    }
}

void global_planner::outline_map(unsigned char *costarr, int nx, int ny, unsigned char value)
{
    unsigned char *pc = costarr;

    for (int i = 0; i < nx; i++)
        *pc++ = value;

    pc = costarr + (ny - 1) * nx;

    for (int i = 0; i < nx; i++)
        *pc++ = value;

    pc = costarr;

    for (int i = 0; i < ny; i++, pc += nx)
        *pc = value;

    pc = costarr + nx - 1;

    for (int i = 0; i < ny; i++, pc += nx)
        *pc = value;
}

global_planner::global_planner() : costmap_(NULL), initialized_(false), allow_unknown_(true),
                                   p_calc_(NULL), planner_(NULL), path_maker_(NULL), orientation_filter_(NULL),
                                   potential_array_(NULL)
{
}

global_planner::global_planner(std::string name, costmap_2d::Costmap2D *costmap, std::string frame_id) : global_planner()
{
    // initialize the planner
    initialize(name, costmap, frame_id);
}

global_planner::~global_planner()
{
    if (p_calc_)
        delete p_calc_;
    if (planner_)
        delete planner_;
    if (path_maker_)
        delete path_maker_;
}

void global_planner::initialize(std::string name, costmap_2d::Costmap2DROS *costmap_ros)
{
    initialize(name, costmap_ros->getCostmap(), costmap_ros->getGlobalFrameID());
}

void global_planner::initialize(std::string name, costmap_2d::Costmap2D *costmap, std::string frame_id)
{
    if (!initialized_)
    {
        ROS_INFO("Dijistra 全局路径规划器已经启动，名称：%s。", name.c_str());

        ros::NodeHandle private_nh("~/" + name);
        ros::NodeHandle global_nh("~");
        costmap_ = costmap;
        frame_id_ = frame_id;

        unsigned int cx = costmap->getSizeInCellsX(), cy = costmap->getSizeInCellsY();

        private_nh.param("old_navfn_behavior", old_navfn_behavior_, false);

        if (!old_navfn_behavior_)
            convert_offset_ = 0.5;
        else
            convert_offset_ = 0.0;

        bool use_quadratic;
        private_nh.param("use_quadratic", use_quadratic, true);

        if (use_quadratic)
            p_calc_ = new QuadraticCalculator(cx, cy);
        else
            p_calc_ = new PotentialCalculator(cx, cy);

        DijkstraExpansion *de = new DijkstraExpansion(p_calc_, cx, cy);
        if (!old_navfn_behavior_)
            de->setPreciseStart(true);
        planner_ = de;

        bool use_grid_path;
        private_nh.param("use_grid_path", use_grid_path, false);

        if (use_grid_path)
            path_maker_ = new GridPath(p_calc_);
        else
            path_maker_ = new GradientPath(p_calc_);

        orientation_filter_ = new OrientationFilter();

        plan_pub_ = private_nh.advertise<nav_msgs::Path>("plan", 1);
        polyline_plan_pub_ = private_nh.advertise<nav_msgs::Path>("polyline_plan", 1);
        potential_pub_ = private_nh.advertise<nav_msgs::OccupancyGrid>("potential", 1);

        private_nh.param("allow_unknown", allow_unknown_, true);
        planner_->setHasUnknown(allow_unknown_);
        private_nh.param("planner_window_x", planner_window_x_, 0.0);
        private_nh.param("planner_window_y", planner_window_y_, 0.0);
        private_nh.param("default_tolerance", default_tolerance_, 0.0);
        private_nh.param("publish_scale", publish_scale_, 100);
        private_nh.param("outline_map", outline_map_, true);

        private_nh.param("occupied_threshold", occupied_threshold_default_, 55);
        private_nh.param("min_dist_to_obs", min_dist_to_obs_default_, 0.26f);

        private_nh.param("lethal_cost", lethal_cost_, 253);
        private_nh.param("neutral_cost", neutral_cost_, 66);
        private_nh.param("cost_factor", cost_factor_, 0.55);

        planner_->setLethalCost(lethal_cost_);
        planner_->setNeutralCost(neutral_cost_);
        planner_->setFactor(cost_factor_);

        // 足迹部分
        XmlRpc::XmlRpcValue footprint_param;
        global_nh.getParam("footprint", footprint_param);

        for (int i = 0; i < footprint_param.size(); i++)
        {
            std::vector<float> point_vector;

            for (int j = 0; j < footprint_param[i].size(); j++)
            {
                point_vector.push_back(double(footprint_param[i][j]));
            }

            geometry_msgs::Point32 point;

            point.x = point_vector[0];
            point.y = point_vector[1];

            footprint_polygon.points.push_back(point);

            ROS_WARN("footprint: %f %f", point.x, point.y);
        }

        initialized_ = true;
    }
    else
        ROS_WARN("全局路径规划器已经初始化，无动作。");
}

void global_planner::clear_robot_cell(const geometry_msgs::PoseStamped &global_pose, unsigned int mx, unsigned int my)
{
    if (!initialized_)
    {
        ROS_ERROR("全局路径规划器尚未初始化。");
        return;
    }

    // set the associated costs in the cost map to be free
    costmap_->setCost(mx, my, costmap_2d::FREE_SPACE);
}

void global_planner::map_to_world(double mx, double my, double &wx, double &wy)
{
    wx = costmap_->getOriginX() + (mx + convert_offset_) * costmap_->getResolution();
    wy = costmap_->getOriginY() + (my + convert_offset_) * costmap_->getResolution();
}

bool global_planner::world_to_map(double wx, double wy, double &mx, double &my)
{
    double origin_x = costmap_->getOriginX(), origin_y = costmap_->getOriginY();
    double resolution = costmap_->getResolution();

    if (wx < origin_x || wy < origin_y)
        return false;

    mx = (wx - origin_x) / resolution - convert_offset_;
    my = (wy - origin_y) / resolution - convert_offset_;

    if (mx < costmap_->getSizeInCellsX() && my < costmap_->getSizeInCellsY())
        return true;

    return false;
}

bool global_planner::make_plan(const geometry_msgs::PoseStamped &start, const geometry_msgs::PoseStamped &goal,
                               std::vector<geometry_msgs::PoseStamped> &plan,
                               std::vector<geometry_msgs::PoseStamped> &polyline_plan,
                               float min_dist_to_obs,
                               bool optimize,
                               int sampling_grid_dist,
                               bool polyline,
                               float polyline_sample_max_dist,
                               int polyline_sample_step,
                               int occupied_threshold)
{
    return make_plan(start, goal, default_tolerance_, plan, polyline_plan, min_dist_to_obs, optimize, sampling_grid_dist, polyline, polyline_sample_max_dist, polyline_sample_step, occupied_threshold);
}

bool global_planner::make_plan(const geometry_msgs::PoseStamped &start, const geometry_msgs::PoseStamped &goal,
                               double tolerance, std::vector<geometry_msgs::PoseStamped> &plan,
                               std::vector<geometry_msgs::PoseStamped> &polyline_plan,
                               float min_dist_to_obs,
                               bool optimize,
                               int sampling_grid_dist,
                               bool polyline,
                               float polyline_sample_max_dist,
                               int polyline_sample_step,
                               int occupied_threshold)
{
    nav_msgs::OccupancyGrid grid_empty;
    grid_empty.data.clear();

    return make_plan(start, goal, tolerance, plan, polyline_plan, grid_empty, min_dist_to_obs, optimize, sampling_grid_dist, polyline, polyline_sample_max_dist, polyline_sample_step, occupied_threshold);
}

bool global_planner::make_plan(const geometry_msgs::PoseStamped &start, const geometry_msgs::PoseStamped &goal,
                               double tolerance, std::vector<geometry_msgs::PoseStamped> &plan,
                               std::vector<geometry_msgs::PoseStamped> &polyline_plan,
                               nav_msgs::OccupancyGrid &grid,
                               float min_dist_to_obs,
                               bool optimize,
                               int sampling_grid_dist,
                               bool polyline,
                               float polyline_sample_max_dist,
                               int polyline_sample_step,
                               int occupied_threshold)
{
    boost::mutex::scoped_lock lock(mutex_);

    if (!initialized_)
    {
        ROS_ERROR("全局路径规划器尚未初始化。");

        return false;
    }

    plan.clear();
    polyline_plan.clear();

    ros::NodeHandle n;
    std::string global_frame = frame_id_;

    if (goal.header.frame_id != global_frame)
    {
        ROS_ERROR("目标点必须在 %s 坐标系下，当前在 %s 坐标系下。",
                  global_frame.c_str(), goal.header.frame_id.c_str());

        return false;
    }

    if (start.header.frame_id != global_frame)
    {
        ROS_ERROR("起点必须在 %s 坐标系下，当前在 %s 坐标系下。",
                  global_frame.c_str(), start.header.frame_id.c_str());

        return false;
    }

    double wx = start.pose.position.x;
    double wy = start.pose.position.y;

    unsigned int start_x_i, start_y_i, goal_x_i, goal_y_i;
    double start_x, start_y, goal_x, goal_y;

    if (!costmap_->worldToMap(wx, wy, start_x_i, start_y_i))
    {
        ROS_WARN("机器人位姿不在代价地图中。");

        return false;
    }
    if (old_navfn_behavior_)
    {
        start_x = start_x_i;
        start_y = start_y_i;
    }
    else
    {
        world_to_map(wx, wy, start_x, start_y);
    }

    wx = goal.pose.position.x;
    wy = goal.pose.position.y;

    if (!costmap_->worldToMap(wx, wy, goal_x_i, goal_y_i))
    {
        ROS_WARN_THROTTLE(1.0, "目标点不在代价地图中。");
        return false;
    }
    if (old_navfn_behavior_)
    {
        goal_x = goal_x_i;
        goal_y = goal_y_i;
    }
    else
    {
        world_to_map(wx, wy, goal_x, goal_y);
    }

    clear_robot_cell(start, start_x_i, start_y_i);

    int nx = costmap_->getSizeInCellsX(), ny = costmap_->getSizeInCellsY();

    p_calc_->setSize(nx, ny);
    planner_->setSize(nx, ny);
    path_maker_->setSize(nx, ny);
    potential_array_ = new float[nx * ny];

    if (outline_map_)
        outline_map(costmap_->getCharMap(), nx, ny, costmap_2d::LETHAL_OBSTACLE);

    // 预处理每个点上最近障碍距离
    compute_obstacle_shortest_distances(costmap_,
                                        occupied_threshold,
                                        shortest_distances,
                                        shortest_distance_coordinates,
                                        grid,
                                        start,
                                        goal,
                                        min_dist_to_obs);

    planner_->shortest_distances_ = shortest_distances;
    planner_->shortest_distance_coordinates_ = shortest_distance_coordinates;

    // 更新距离障碍最短距离
    planner_->min_dist_to_obs_ = min_dist_to_obs;

    bool found_legal = planner_->calculatePotentials(costmap_->getCharMap(), start_x, start_y, goal_x, goal_y,
                                                     nx * ny * 2, potential_array_);

    if (!old_navfn_behavior_)
        planner_->clearEndpoint(costmap_->getCharMap(), potential_array_, goal_x_i, goal_y_i, 2);
    if (publish_potential_)
        publish_potential(potential_array_);

    if (found_legal)
    {
        if (get_plan_from_potential(start_x, start_y, goal_x, goal_y, goal, plan, polyline_plan,
                                    min_dist_to_obs, optimize, sampling_grid_dist,
                                    polyline, polyline_sample_max_dist, polyline_sample_step))
        {
            geometry_msgs::PoseStamped goal_copy = goal;
            goal_copy.header.stamp = ros::Time::now();

            plan.push_back(goal_copy);
        }
        else
        {
            ROS_ERROR("无法获取路径。");
        }
    }
    else
    {
        ROS_ERROR("无法获取路径。");
    }

    orientation_filter_->processPath(start, plan);

    if (plan.size() > 0)
        publish_plan(plan);

    if (polyline_plan.size() > 0)
        publish_polyline_plan(polyline_plan);

    delete[] potential_array_;

    return !plan.empty();
}

void global_planner::publish_plan(const std::vector<geometry_msgs::PoseStamped> &path)
{
    if (!initialized_)
    {
        ROS_ERROR("全局路径规划器尚未初始化。");

        return;
    }

    nav_msgs::Path gui_path;
    gui_path.poses.resize(path.size());

    gui_path.header.frame_id = frame_id_;
    gui_path.header.stamp = ros::Time::now();

    for (unsigned int i = 0; i < path.size(); i++)
    {
        gui_path.poses[i] = path[i];
    }

    plan_pub_.publish(gui_path);
}

void global_planner::publish_polyline_plan(const std::vector<geometry_msgs::PoseStamped> &path)
{
    if (!initialized_)
    {
        ROS_ERROR("全局路径规划器尚未初始化。");

        return;
    }

    nav_msgs::Path gui_path;
    gui_path.poses.resize(path.size());

    gui_path.header.frame_id = frame_id_;
    gui_path.header.stamp = ros::Time::now();

    for (unsigned int i = 0; i < path.size(); i++)
    {
        gui_path.poses[i] = path[i];
    }

    polyline_plan_pub_.publish(gui_path);
}

bool global_planner::get_plan_from_potential(double start_x, double start_y, double goal_x, double goal_y,
                                             const geometry_msgs::PoseStamped &goal,
                                             std::vector<geometry_msgs::PoseStamped> &plan,
                                             std::vector<geometry_msgs::PoseStamped> &polyline_plan,
                                             float min_dist_to_obs,
                                             bool optimize,
                                             int sampling_grid_dist,
                                             bool polyline,
                                             float polyline_sample_max_dist,
                                             int polyline_sample_step)
{
    if (!initialized_)
    {
        ROS_ERROR("全局路径规划器尚未初始化。");

        return false;
    }

    std::string global_frame = frame_id_;

    plan.clear();
    polyline_plan.clear();

    std::vector<std::pair<float, float>> path;

    if (!path_maker_->getPath(potential_array_, start_x, start_y, goal_x, goal_y, path))
    {
        ROS_ERROR("未找到路径。");

        return false;
    }

    std::vector<std::pair<float, float>> path_final;
    std::vector<std::pair<float, float>> path_polyline;

    if (optimize && !polyline)
    {
        if (!path_optimizer)
        {
            path_optimizer = make_unique<backend_optimization::backend_optimizer>();
        }

        auto result = path_optimizer->optimize(path,
                                               costmap_->getSizeInCellsX(),
                                               costmap_->getSizeInCellsY(),
                                               costmap_->getResolution(),
                                               sampling_grid_dist,
                                               min_dist_to_obs,
                                               shortest_distances);

        if (get<0>(result))
        {
            // ROS_INFO("路径优化成功！");
        }
        else
        {
            ROS_ERROR("路径优化失败！");
        }

        path_final = get<1>(result);
    }
    else if (polyline)
    {
        // if (optimize)
        // {

        // }

        if (!path_polylineizer)
        {
            path_polylineizer = make_unique<polyline_generation::polyline_generator>();
        }

        auto result = path_polylineizer->generate(path,
                                                  costmap_->getSizeInCellsX(),
                                                  costmap_->getSizeInCellsY(),
                                                  costmap_->getResolution(),
                                                  sampling_grid_dist,
                                                  min_dist_to_obs,
                                                  polyline_sample_max_dist,
                                                  polyline_sample_step,
                                                  shortest_distances);

        if (get<0>(result))
        {
            // ROS_INFO("路径优化成功！");
        }
        else
        {
            ROS_ERROR("路径折线化失败！");
        }

        path_final = get<1>(result);
        path_polyline = get<2>(result);
    }
    else
    {
        path_final = path;
    }

    ros::Time plan_time = ros::Time::now();

    for (int i = path_final.size() - 1; i >= 0; i--)
    {
        std::pair<float, float> point = path_final[i];

        double world_x, world_y;
        map_to_world(point.first, point.second, world_x, world_y);

        geometry_msgs::PoseStamped pose;
        pose.header.stamp = plan_time;
        pose.header.frame_id = global_frame;
        pose.pose.position.x = world_x;
        pose.pose.position.y = world_y;
        pose.pose.position.z = 0.0;
        pose.pose.orientation.x = 0.0;
        pose.pose.orientation.y = 0.0;
        pose.pose.orientation.z = 0.0;
        pose.pose.orientation.w = 1.0;
        plan.push_back(pose);
    }

    if (old_navfn_behavior_)
    {
        plan.push_back(goal);
    }

    plan = calc_path_orientation(plan);

    if (path_polyline.size() > 0)
    {
        for (int i = path_polyline.size() - 1; i >= 1; i--)
        {
            std::pair<float, float> point = path_polyline[i];

            double world_x, world_y;
            map_to_world(point.first, point.second, world_x, world_y);

            geometry_msgs::PoseStamped pose;
            pose.header.stamp = plan_time;
            pose.header.frame_id = global_frame;
            pose.pose.position.x = world_x;
            pose.pose.position.y = world_y;
            pose.pose.position.z = 0.0;
            pose.pose.orientation.x = 0.0;
            pose.pose.orientation.y = 0.0;
            pose.pose.orientation.z = 0.0;
            pose.pose.orientation.w = 1.0;
            polyline_plan.push_back(pose);
        }

        polyline_plan.push_back(goal);

        for (int i = 0; i < polyline_plan.size() - 1; i++)
        {
            double x0 = polyline_plan[i].pose.position.x;
            double y0 = polyline_plan[i].pose.position.y;
            double x1 = polyline_plan[i + 1].pose.position.x;
            double y1 = polyline_plan[i + 1].pose.position.y;

            polyline_plan[i].pose.orientation = tf::createQuaternionMsgFromYaw(std::atan2(y1 - y0, x1 - x0));
        }
    }

    return !plan.empty();
}

void global_planner::publish_potential(float *potential)
{
    int nx = costmap_->getSizeInCellsX(), ny = costmap_->getSizeInCellsY();
    double resolution = costmap_->getResolution();
    nav_msgs::OccupancyGrid grid;

    grid.header.frame_id = frame_id_;
    grid.header.stamp = ros::Time::now();
    grid.info.resolution = resolution;

    grid.info.width = nx;
    grid.info.height = ny;

    double wx, wy;
    costmap_->mapToWorld(0, 0, wx, wy);
    grid.info.origin.position.x = wx - resolution / 2;
    grid.info.origin.position.y = wy - resolution / 2;
    grid.info.origin.position.z = 0.0;
    grid.info.origin.orientation.w = 1.0;

    grid.data.resize(nx * ny);

    float max = 0.0;

    for (unsigned int i = 0; i < grid.data.size(); i++)
    {
        float potential = potential_array_[i];
        if (potential < POT_HIGH)
        {
            if (potential > max)
            {
                max = potential;
            }
        }
    }

    for (unsigned int i = 0; i < grid.data.size(); i++)
    {
        if (potential_array_[i] >= POT_HIGH)
        {
            grid.data[i] = -1;
        }
        else
        {
            if (fabs(max) < DBL_EPSILON)
            {
                grid.data[i] = -1;
            }
            else
            {
                grid.data[i] = potential_array_[i] * publish_scale_ / max;
            }
        }
    }

    potential_pub_.publish(grid);
}
