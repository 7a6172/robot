#include <navigation/utils/math_utils.h>

boost::uuids::random_generator uuid_generator;

geometry_msgs::Polygon transform_footprint(geometry_msgs::PoseWithCovarianceStamped &pose,
                                           geometry_msgs::Polygon &footprint)
{
    geometry_msgs::Polygon ret;

    ret.points.clear();

    size_t size = footprint.points.size();

    for (int i = 0; i < size; i++)
    {
        geometry_msgs::Point32 point;

        float x = footprint.points[i].x;
        float y = footprint.points[i].y;
        float yaw = tf::getYaw(pose.pose.pose.orientation);

        // 将足迹转换到当前 pose 坐标系下
        point.x = pose.pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
        point.y = pose.pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));

        ret.points.push_back(point);
    }

    return ret;
}

tuple<vector<obstacle_line>, vector<float>> create_obstacle_lines(geometry_msgs::PoseWithCovarianceStamped &pose,
                                                                  geometry_msgs::Polygon &footprint,
                                                                  openmover_msgs::obstacle &obstacle)
{
    tuple<vector<obstacle_line>, vector<float>> ret;

    get<0>(ret).clear();
    get<1>(ret).clear();

    // 先转换至 base_link 坐标系，再转换至 pose 坐标系比较简单
    // 处理前部数据，从左至右为 4 3 2 1 0
    size_t size = obstacle.obstacle_forward.size();

    // 从 footprint 计算宽度
    float width = abs(footprint.points[1].y - footprint.points[0].y);

    // 计算每个网格宽度
    float width_per_grid = width / (float)size;

    // 每个栅格中最近障碍距离
    float min_dist = INFINITY;

    for (int i = 0; i < size; i++)
    {
        if (obstacle.obstacle_forward[i] != INFINITY)
        {
            obstacle_line line;

            line.type == obstacle_line_type::FRONT;

            // x 以障碍距离定义
            line.p0.x = obstacle.obstacle_forward[i] + min(footprint.points[0].x, footprint.points[1].x);
            line.p1.x = line.p0.x;
            min_dist = min(min_dist, obstacle.obstacle_forward[i]);

            // y 以网格定义
            line.p0.y = i * width_per_grid - width / 2.0;
            line.p1.y = (i + 1) * width_per_grid - width / 2.0;

            // 转换坐标系
            float x = line.p0.x;
            float y = line.p0.y;
            float yaw = tf::getYaw(pose.pose.pose.orientation);

            line.p0.x = pose.pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
            line.p0.y = pose.pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));

            x = line.p1.x;
            y = line.p1.y;

            line.p1.x = pose.pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
            line.p1.y = pose.pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));

            get<0>(ret).push_back(line);
        }
    }

    get<1>(ret).push_back(min_dist);

    // 处理后部数据，从左至右为 0 1 2 3 4
    size = obstacle.obstacle_backward.size();

    // 从 footprint 计算宽度
    width = abs(footprint.points[2].y - footprint.points[3].y);

    // 计算每个网格宽度
    width_per_grid = width / (float)size;

    // 每个栅格中最近障碍距离
    min_dist = INFINITY;

    for (int i = 0; i < size; i++)
    {
        if (obstacle.obstacle_backward[i] != INFINITY)
        {
            obstacle_line line;

            line.type == obstacle_line_type::REAR;

            // x 以障碍距离定义
            line.p0.x = -obstacle.obstacle_backward[i] + max(footprint.points[2].x, footprint.points[3].x);
            line.p1.x = line.p0.x;
            min_dist = min(min_dist, obstacle.obstacle_backward[i]);

            // y 以网格定义
            line.p0.y = (width / 2.0) - (i * width_per_grid);
            line.p1.y = (width / 2.0) - ((i + 1) * width_per_grid);

            // 转换坐标系
            float x = line.p0.x;
            float y = line.p0.y;
            float yaw = tf::getYaw(pose.pose.pose.orientation);

            line.p0.x = pose.pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
            line.p0.y = pose.pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));

            x = line.p1.x;
            y = line.p1.y;

            line.p1.x = pose.pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
            line.p1.y = pose.pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));

            get<0>(ret).push_back(line);
        }
    }

    get<1>(ret).push_back(min_dist);

    // 处理左部数据，从上至下为 0 1 2 3 4
    size = obstacle.obstacle_left.size();

    // 从 footprint 计算长度
    float length = abs(footprint.points[0].x - footprint.points[3].x);

    // 计算每个网格宽度
    float length_per_grid = length / (float)size;

    // 每个栅格中最近障碍距离
    min_dist = INFINITY;

    for (int i = 0; i < size; i++)
    {
        if (obstacle.obstacle_left[i] != INFINITY)
        {
            obstacle_line line;

            line.type == obstacle_line_type::LEFT;

            // y 以障碍距离定义
            line.p0.y = obstacle.obstacle_left[i] + min(footprint.points[0].y, footprint.points[3].y);
            line.p1.y = line.p0.y;

            // x 以网格定义
            line.p0.x = (length / 2.0) - (i * length_per_grid);
            line.p1.x = (length / 2.0) - ((i + 1) * length_per_grid);
            min_dist = min(min_dist, obstacle.obstacle_left[i]);

            // 转换坐标系
            float x = line.p0.x;
            float y = line.p0.y;
            float yaw = tf::getYaw(pose.pose.pose.orientation);

            line.p0.x = pose.pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
            line.p0.y = pose.pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));

            x = line.p1.x;
            y = line.p1.y;

            line.p1.x = pose.pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
            line.p1.y = pose.pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));

            get<0>(ret).push_back(line);
        }
    }

    get<1>(ret).push_back(min_dist);

    // 处理右部数据，从下至上为 0 1 2 3 4
    size = obstacle.obstacle_right.size();

    // 从 footprint 计算长度
    length = abs(footprint.points[1].x - footprint.points[2].x);

    // 计算每个网格宽度
    length_per_grid = length / (float)size;

    // 每个栅格中最近障碍距离
    min_dist = INFINITY;

    for (int i = 0; i < size; i++)
    {
        if (obstacle.obstacle_right[i] != INFINITY)
        {
            obstacle_line line;

            line.type == obstacle_line_type::RIGHT;

            // y 以障碍距离定义
            line.p0.y = -obstacle.obstacle_right[i] + max(footprint.points[1].y, footprint.points[2].y);
            line.p1.y = line.p0.y;
            min_dist = min(min_dist, obstacle.obstacle_right[i]);

            // x 以网格定义
            line.p0.x = (i * length_per_grid) - (length / 2.0);
            line.p1.x = ((i + 1) * length_per_grid) - (length / 2.0);

            // 转换坐标系
            float x = line.p0.x;
            float y = line.p0.y;
            float yaw = tf::getYaw(pose.pose.pose.orientation);

            line.p0.x = pose.pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
            line.p0.y = pose.pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));

            x = line.p1.x;
            y = line.p1.y;

            line.p1.x = pose.pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
            line.p1.y = pose.pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));

            get<0>(ret).push_back(line);
        }
    }

    get<1>(ret).push_back(min_dist);

    return ret;
}

int orientation(const geometry_msgs::Point32 &p, const geometry_msgs::Point32 &q, const geometry_msgs::Point32 &r)
{
    double val = (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y);

    if (fabs(val) < 1e-10)
    {
        return 0;
    }

    return (val > 0) ? 1 : 2;
}

bool on_segment(const geometry_msgs::Point32 &p, const geometry_msgs::Point32 &q, const geometry_msgs::Point32 &r)
{
    return (q.x <= max(p.x, r.x) && q.x >= min(p.x, r.x) &&
            q.y <= max(p.y, r.y) && q.y >= min(p.y, r.y));
}

bool is_intersect(const geometry_msgs::Point32 &p1,
                  const geometry_msgs::Point32 &p2,
                  const geometry_msgs::Point32 &p3,
                  const geometry_msgs::Point32 &p4)
{
    // 检查线段p1p2和p3p4是否相交
    int o1 = orientation(p3, p4, p1);
    int o2 = orientation(p3, p4, p2);
    int o3 = orientation(p1, p2, p3);
    int o4 = orientation(p1, p2, p4);

    // 如果两个线段相互跨越，则它们相交
    if (o1 != o2 && o3 != o4)
    {
        return true;
    }

    // 当两条线段共线时，检查是否重叠
    if (o1 == 0 && on_segment(p3, p1, p4))
    {
        return true;
    }
    if (o2 == 0 && on_segment(p3, p2, p4))
    {
        return true;
    }
    if (o3 == 0 && on_segment(p1, p3, p2))
    {
        return true;
    }
    if (o4 == 0 && on_segment(p1, p4, p2))
    {
        return true;
    }

    // 其他情况，线段不相交
    return false;
}

bool is_point_in_rect(const geometry_msgs::Point32 &p, const geometry_msgs::Polygon &rect)
{
    int count = 0;

    // 射线法求解凸多边形线段包含
    size_t size = rect.points.size();

    for (unsigned int i = 0; i < size; i++)
    {
        geometry_msgs::Point32 a = rect.points[i];
        geometry_msgs::Point32 b = rect.points[(i + 1) % size];

        if ((a.y <= p.y && b.y > p.y) || (b.y <= p.y && a.y > p.y))
        {
            double t = (p.y - a.y) / (double)(b.y - a.y);

            if (a.x + t * (b.x - a.x) > p.x)
            {
                count++;
            }
        }
    }

    return count % 2 != 0;
}

bool is_point_in_obstacle(const geometry_msgs::Point32 &p, const obstacle_description &ob)
{
    if (ob.type == CONVEX)
    {
        geometry_msgs::Polygon rect;

        for (const auto &line : ob.boundaries)
        {
            rect.points.push_back(line.p0);
        }

        return is_point_in_rect(p, rect);
    }
    else if (ob.type == CIRCLE)
    {
        float dist = calculate_distance(p, ob.center);

        return dist <= ob.radius;
    }

    return false;
}

bool is_line_intersect_rect(geometry_msgs::Polygon &polygon, vector<obstacle_line> &lines)
{
    geometry_msgs::Point32 top_right = polygon.points[0];
    geometry_msgs::Point32 top_left = polygon.points[1];
    geometry_msgs::Point32 bottom_left = polygon.points[2];
    geometry_msgs::Point32 bottom_right = polygon.points[3];

    for (auto line : lines)
    {
        // 若线段与多边形任意一边相交或包含在多边形内，则发生冲突
        if (is_intersect(top_left, top_right, line.p0, line.p1) ||
            is_intersect(top_right, bottom_right, line.p0, line.p1) ||
            is_intersect(bottom_right, bottom_left, line.p0, line.p1) ||
            is_intersect(bottom_left, top_left, line.p0, line.p1) ||
            (is_point_in_rect(line.p0, polygon) && is_point_in_rect(line.p1, polygon)))
        {
            return true;
        }
    }

    return false;
}

bool is_rect_intersect(const obstacle_description &rect1, const obstacle_description &rect2)
{
    for (auto line1 : rect1.boundaries)
    {
        for (auto line2 : rect2.boundaries)
        {
            if (is_intersect(line1.p0, line1.p1, line2.p0, line2.p1))
            {
                return true;
            }
        }
    }

    return false;
}

bool is_obstacle_intersect(const obstacle_description &ob1, const obstacle_description &ob2)
{
    if (ob1.type == CIRCLE && ob2.type == CIRCLE)
    {
        if (calculate_distance(ob1.center, ob2.center) < (ob1.radius + ob2.radius))
        {
            return true;
        }
    }
    else if (ob1.type == CONVEX && ob2.type == CONVEX)
    {
        // 检查一个矩形的顶点是否在另一个矩形内
        for (auto line : ob1.boundaries)
        {
            if (is_point_in_obstacle(line.p0, ob2))
            {
                return true;
            }
        }

        for (auto line : ob2.boundaries)
        {
            if (is_point_in_obstacle(line.p0, ob1))
            {
                return true;
            }
        }

        if (is_rect_intersect(ob1, ob2))
        {
            return true;
        }
    }
    else
    {
        obstacle_description circle = (ob1.type == CIRCLE) ? ob1 : ob2;
        obstacle_description rect = (ob1.type == CONVEX) ? ob1 : ob2;

        if (is_point_in_obstacle(circle.center, rect))
        {
            return true;
        }

        for (const auto &line : rect.boundaries)
        {
            if (is_line_in_or_cross_circle(circle.center, circle.radius, line))
            {
                return true;
            }
        }
    }

    return false;
}

bool is_obstacle_in_obstacle(const obstacle_description &ob1, const obstacle_description &ob2)
{
    for (const auto &line : ob1.boundaries)
    {
        if (!is_point_in_obstacle(line.p0, ob2))
        {
            return false;
        }
    }

    return true;
}

bool is_obstacle_almost_in_obstacle(const obstacle_description &ob1, const obstacle_description &ob2)
{
    int counter = 0;

    for (const auto &line : ob1.boundaries)
    {
        if (!is_point_in_obstacle(line.p0, ob2))
        {
            counter++;
        }
    }

    return (counter * 1.0 / ob1.boundaries.size()) <= 0.2;
}

float calc_path_point_orientation(geometry_msgs::Pose &pose, vector<geometry_msgs::Pose> &forward_points)
{
    float avg_dx = 0.0;
    float avg_dy = 0.0;
    int num_points = 0;

    // 计算平均向量
    for (const auto &point : forward_points)
    {
        float dx = point.position.x - pose.position.x;
        float dy = point.position.y - pose.position.y;

        float distance = sqrt(dx * dx + dy * dy);

        // 如果点在给定的距离范围内，则考虑它
        if (distance <= 0.05)
        {
            avg_dx += dx;
            avg_dy += dy;
            num_points++;
        }
        else
        {
            // 如果超出了距离范围，就停止循环
            break;
        }
    }

    if (num_points > 0)
    {
        avg_dx /= (float)num_points;
        avg_dy /= (float)num_points;
    }

    // 计算平均向量的角度
    float avg_orientation = atan2(avg_dy, avg_dx);

    return avg_orientation;
}

obstacle_description circle_to_convex(float cx, float cy, float r, int subdivisions)
{
    obstacle_description ret;

    vector<geometry_msgs::Point32> vertices;

    double angle_increment = 2 * M_PI / subdivisions;

    for (int i = 0; i < subdivisions; i++)
    {
        geometry_msgs::Point32 point;

        double angle = i * angle_increment;
        point.x = cx + r * cos(angle);
        point.y = cy + r * sin(angle);

        vertices.push_back(point);
    }

    vector<obstacle_line> obstacle_lines_temp;

    for (int i = 0; i < vertices.size(); i++)
    {
        // 添加到障碍物直线
        obstacle_line line;
        line.p0 = vertices[i];
        line.p1 = vertices[(i + 1) % vertices.size()];

        obstacle_lines_temp.push_back(line);
    }

    ret = create_obstacle(obstacle_lines_temp);

    return ret;
}

bool is_footprint_has_occupied_point(nav_msgs::OccupancyGridConstPtr grid,
                                     geometry_msgs::Polygon &footprint,
                                     const geometry_msgs::PoseStamped &pose,
                                     float stop_distance,
                                     bool reversed,
                                     int sampling_ratio,
                                     float padding_ratio)
{
    // 计算搜索区域的角点
    geometry_msgs::Point32 min_corner, max_corner;
    min_corner.x = pose.pose.position.x - stop_distance * padding_ratio;
    min_corner.y = pose.pose.position.y - stop_distance * padding_ratio;
    max_corner.x = pose.pose.position.x + stop_distance * padding_ratio;
    max_corner.y = pose.pose.position.y + stop_distance * padding_ratio;

    // 将角点坐标转换为占据栅格地图的索引
    int min_x_index = max(0, (int)((min_corner.x - grid->info.origin.position.x) / grid->info.resolution));
    int min_y_index = max(0, (int)((min_corner.y - grid->info.origin.position.y) / grid->info.resolution));
    int max_x_index = min((int)grid->info.width - 1, (int)((max_corner.x - grid->info.origin.position.x) / grid->info.resolution));
    int max_y_index = min((int)grid->info.height - 1, (int)((max_corner.y - grid->info.origin.position.y) / grid->info.resolution));

    // 定义障碍检测区域，先定义到 base_link，进一步变换至 map 中
    geometry_msgs::Polygon obstacle_detection_area;

    // 如果正向驱动，则障碍检测区域由 0 - 1 构成边
    if (!reversed)
    {
        float yaw = tf::getYaw(pose.pose.orientation);

        // 右下角点
        geometry_msgs::Point32 point;
        float x = footprint.points[0].x;
        float y = footprint.points[0].y;
        point.x = pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
        point.y = pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));
        obstacle_detection_area.points.push_back(point);

        // 左下角点
        x = footprint.points[1].x;
        y = footprint.points[1].y;
        point.x = pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
        point.y = pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));
        obstacle_detection_area.points.push_back(point);

        // 左上角点
        x = footprint.points[1].x + stop_distance * padding_ratio;
        y = footprint.points[1].y;
        point.x = pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
        point.y = pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));
        obstacle_detection_area.points.push_back(point);

        // 右上角点
        x = footprint.points[0].x + stop_distance * padding_ratio;
        y = footprint.points[0].y;
        point.x = pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
        point.y = pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));
        obstacle_detection_area.points.push_back(point);
    }
    else
    {
        // 反向驱动，航向角旋转 180 度
        float yaw = angles::normalize_angle(
            tf::getYaw(pose.pose.orientation) + M_PI);

        // 左上角点
        geometry_msgs::Point32 point;
        float x = footprint.points[2].x;
        float y = footprint.points[2].y;
        point.x = pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
        point.y = pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));
        obstacle_detection_area.points.push_back(point);

        // 右上角点
        x = footprint.points[3].x;
        y = footprint.points[3].y;
        point.x = pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
        point.y = pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));
        obstacle_detection_area.points.push_back(point);

        // 右下角点
        x = footprint.points[3].x - stop_distance * padding_ratio;
        y = footprint.points[3].y;
        point.x = pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
        point.y = pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));
        obstacle_detection_area.points.push_back(point);

        // 左下角点
        x = footprint.points[2].x - stop_distance * padding_ratio;
        y = footprint.points[2].y;
        point.x = pose.pose.position.x + (x * cos(yaw) - y * sin(yaw));
        point.y = pose.pose.position.y + (y * cos(yaw) + x * sin(yaw));
        obstacle_detection_area.points.push_back(point);
    }

    // 遍历搜索区域
    for (int i = min_x_index; i <= max_x_index; i += sampling_ratio)
    {
        for (int j = min_y_index; j <= max_y_index; j += sampling_ratio)
        {
            // 计算格子的坐标
            geometry_msgs::Point32 point;
            point.x = grid->info.origin.position.x + i * grid->info.resolution;
            point.y = grid->info.origin.position.y + j * grid->info.resolution;

            // 如果格子在障碍检测区域内
            if (is_point_in_rect(point, obstacle_detection_area))
            {
                // 计算格子的索引
                int index = j * grid->info.width + i;

                // 如果被占据
                if (grid->data[index] >= 66)
                {
                    return true;
                }
            }
        }
    }

    // 如果未被占据
    return false;
}

geometry_msgs::Point32 calculate_polygon_center(const geometry_msgs::Polygon &polygon)
{
    geometry_msgs::Point32 center;

    for (const auto &point : polygon.points)
    {
        center.x += point.x;
        center.y += point.y;
    }

    center.x /= polygon.points.size();
    center.y /= polygon.points.size();

    return center;
}

geometry_msgs::Point32 calculate_line_center(const obstacle_line &line)
{
    geometry_msgs::Point32 center;

    center.x = (line.p0.x + line.p1.x) / 2.0;
    center.y = (line.p0.y + line.p1.y) / 2.0;

    return center;
}

float calculate_distance(const geometry_msgs::Pose &p1, const geometry_msgs::Pose &p2)
{
    return hypot(hypot(p1.position.x - p2.position.x, p1.position.y - p2.position.y), p1.position.z - p2.position.z);
}

float calculate_distance(const geometry_msgs::Point32 &p1, const geometry_msgs::Point32 &p2)
{
    return hypot(hypot(p1.x - p2.x, p1.y - p2.y), p1.z - p2.z);
}

float calculate_distance(const octomap::point3d &p1, const octomap::point3d &p2)
{
    return hypot(hypot(p1.x() - p2.x(), p1.y() - p2.y()), p1.z() - p2.z());
}

float calculate_distance(const cv::Point2f &p1, const cv::Point2f &p2)
{
    return hypot(p1.x - p2.x, p1.y - p2.y);
}

float calculate_distance(const pcl::PointXY &p1, const pcl::PointXY &p2)
{
    return hypot(p1.x - p2.x, p1.y - p2.y);
}

float calculate_distance(const pcl::PointXYZ &p1, const pcl::PointXYZ &p2)
{
    return hypot(hypot(p1.x - p2.x, p1.y - p2.y), p1.z - p2.z);
}

geometry_msgs::Point32 create_point(const float &x, const float &y)
{
    geometry_msgs::Point32 ret;

    ret.x = x;
    ret.y = y;

    return ret;
}

geometry_msgs::Point32 create_point(const float &x, const float &y, const float &z)
{
    geometry_msgs::Point32 ret = create_point(x, y);

    ret.z = z;

    return ret;
}

geometry_msgs::Point create_pointd(const float &x, const float &y)
{
    geometry_msgs::Point ret;

    ret.x = x;
    ret.y = y;

    return ret;
}

geometry_msgs::Point create_pointd(const float &x, const float &y, const float &z)
{
    geometry_msgs::Point ret = create_pointd(x, y);

    ret.z = z;

    return ret;
}

geometry_msgs::Point point_ros_to_rosd(const geometry_msgs::Point32 &p)
{
    geometry_msgs::Point ret;

    ret.x = p.x;
    ret.y = p.y;
    ret.z = p.z;

    return ret;
}

octomap::point3d point_ros_to_octomap(const geometry_msgs::Point32 &p)
{
    return octomap::point3d(p.x, p.y, p.z);
}

geometry_msgs::Point32 point_octomap_to_ros(const octomap::point3d &p)
{
    geometry_msgs::Point32 ret;

    ret.x = p.x();
    ret.y = p.y();
    ret.z = p.z();

    return ret;
}

cv::Point2f point_ros_to_cv(const geometry_msgs::Point32 &p)
{
    return cv::Point2f(p.x, p.y);
}

geometry_msgs::Point32 point_cv_to_ros(const cv::Point2f &p)
{
    geometry_msgs::Point32 ret;

    ret.x = p.x;
    ret.y = p.y;
    ret.z = 0.0;

    return ret;
}

geometry_msgs::Point point_cv_to_rosd(const cv::Point2f &p)
{
    geometry_msgs::Point ret;

    ret.x = p.x;
    ret.y = p.y;
    ret.z = 0.0;

    return ret;
}

geometry_msgs::Point32 point_pcl_xyz_to_ros(const pcl::PointXYZ &p)
{
    geometry_msgs::Point32 ret;

    ret.x = p.x;
    ret.y = p.y;
    ret.z = p.z;

    return ret;
}

geometry_msgs::Point32 point_pcl_xyzrgb_to_ros(const pcl::PointXYZRGB &p)
{
    geometry_msgs::Point32 ret;

    ret.x = p.x;
    ret.y = p.y;
    ret.z = p.z;

    return ret;
}

pcl::PointXYZRGB point_ros_to_pcl_xyzrgb(const geometry_msgs::Point32 &p)
{
    pcl::PointXYZRGB ret;

    ret.x = p.x;
    ret.y = p.y;
    ret.z = p.z;

    return ret;
}

geometry_msgs::Point point_pcl_xyz_to_rosd(const pcl::PointXYZ &p)
{
    geometry_msgs::Point ret;

    ret.x = p.x;
    ret.y = p.y;
    ret.z = p.z;

    return ret;
}

geometry_msgs::Point point_pcl_xyzrgb_to_rosd(const pcl::PointXYZRGB &p)
{
    geometry_msgs::Point ret;

    ret.x = p.x;
    ret.y = p.y;
    ret.z = p.z;

    return ret;
}

geometry_msgs::Polygon points_to_polygon(const vector<geometry_msgs::Point32> &points)
{
    geometry_msgs::Polygon polygon;

    for (const auto &p : points)
    {
        polygon.points.push_back(p);
    }

    return polygon;
}

geometry_msgs::Polygon points_to_polygon(const vector<octomap::point3d> &points)
{
    geometry_msgs::Polygon polygon;

    for (const auto &p : points)
    {
        polygon.points.push_back(point_octomap_to_ros(p));
    }

    return polygon;
}

geometry_msgs::Polygon points_to_polygon(const vector<cv::Point2f> &points)
{
    geometry_msgs::Polygon polygon;

    for (const auto &p : points)
    {
        polygon.points.push_back(point_cv_to_ros(p));
    }

    return polygon;
}

geometry_msgs::Polygon points_to_polygon(const geometry_msgs::Point32 &p0,
                                         const geometry_msgs::Point32 &p1,
                                         const geometry_msgs::Point32 &p2,
                                         const geometry_msgs::Point32 &p3)
{
    return points_to_polygon(vector<geometry_msgs::Point32>{p0, p1, p2, p3});
}

geometry_msgs::Polygon points_to_polygon(const octomap::point3d &p0,
                                         const octomap::point3d &p1,
                                         const octomap::point3d &p2,
                                         const octomap::point3d &p3)
{
    return points_to_polygon(vector<octomap::point3d>{p0, p1, p2, p3});
}

geometry_msgs::Polygon points_to_polygon(const cv::Point2f &p0,
                                         const cv::Point2f &p1,
                                         const cv::Point2f &p2,
                                         const cv::Point2f &p3)
{
    return points_to_polygon(vector<cv::Point2f>{p0, p1, p2, p3});
}

tuple<geometry_msgs::Point32, geometry_msgs::Point32> get_box_aabb(const geometry_msgs::Polygon &polygon)
{
    float min_x = numeric_limits<float>::max();
    float min_y = numeric_limits<float>::max();
    float max_x = -numeric_limits<float>::max();
    float max_y = -numeric_limits<float>::max();

    for (const auto &point : polygon.points)
    {
        min_x = min(min_x, point.x);
        min_y = min(min_y, point.y);
        max_x = max(max_x, point.x);
        max_y = max(max_y, point.y);
    }

    geometry_msgs::Point32 min_point, max_point;

    min_point.x = min_x;
    min_point.y = min_y;
    min_point.z = 0;

    max_point.x = max_x;
    max_point.y = max_y;
    max_point.z = 0;

    return {min_point, max_point};
}

tuple<geometry_msgs::Point32, geometry_msgs::Point32> get_box_aabb(const obstacle_description &obstacle)
{
    geometry_msgs::Point32 min_point, max_point;

    if (obstacle.type == obstacle_type::CONVEX)
    {
        min_point.x = min_point.y = numeric_limits<float>::max();
        max_point.x = max_point.y = -numeric_limits<float>::max();

        for (const auto &boundary : obstacle.boundaries)
        {
            min_point.x = min({min_point.x, boundary.p0.x, boundary.p1.x});
            min_point.y = min({min_point.y, boundary.p0.y, boundary.p1.y});
            max_point.x = max({max_point.x, boundary.p0.x, boundary.p1.x});
            max_point.y = max({max_point.y, boundary.p0.y, boundary.p1.y});
        }
    }
    else if (obstacle.type == obstacle_type::CIRCLE)
    {
        min_point.x = obstacle.center.x - obstacle.radius;
        min_point.y = obstacle.center.y - obstacle.radius;
        max_point.x = obstacle.center.x + obstacle.radius;
        max_point.y = obstacle.center.y + obstacle.radius;
    }

    return {min_point, max_point};
}

tuple<int, int, int, int> get_box_aabb_in_grid(const geometry_msgs::Polygon &polygon, const nav_msgs::OccupancyGrid &grid)
{
    auto [min_point, max_point] = get_box_aabb(polygon);

    int min_x = max(0, static_cast<int>((min_point.x - grid.info.origin.position.x) / grid.info.resolution));
    int min_y = max(0, static_cast<int>((min_point.y - grid.info.origin.position.y) / grid.info.resolution));
    int max_x = min(static_cast<int>(grid.info.width), static_cast<int>((max_point.x - grid.info.origin.position.x) / grid.info.resolution));
    int max_y = min(static_cast<int>(grid.info.height), static_cast<int>((max_point.y - grid.info.origin.position.y) / grid.info.resolution));

    return {min_x, max_x, min_y, max_y};
}

tuple<int, int, int, int> get_box_aabb_in_grid(const obstacle_description &obstacle, const nav_msgs::OccupancyGrid &grid)
{
    auto [min_point, max_point] = get_box_aabb(obstacle);

    int min_x = max(0, static_cast<int>((min_point.x - grid.info.origin.position.x) / grid.info.resolution));
    int min_y = max(0, static_cast<int>((min_point.y - grid.info.origin.position.y) / grid.info.resolution));
    int max_x = min(static_cast<int>(grid.info.width), static_cast<int>((max_point.x - grid.info.origin.position.x) / grid.info.resolution));
    int max_y = min(static_cast<int>(grid.info.height), static_cast<int>((max_point.y - grid.info.origin.position.y) / grid.info.resolution));

    return {min_x, max_x, min_y, max_y};
}

geometry_msgs::Point32 grid_xy_to_position(const int &x, const int &y, const nav_msgs::OccupancyGrid &grid)
{
    geometry_msgs::Point32 position;

    position.x = grid.info.origin.position.x + (x + 0.5) * grid.info.resolution;
    position.y = grid.info.origin.position.y + (y + 0.5) * grid.info.resolution;
    position.z = 0;

    return position;
}

geometry_msgs::Point32 grid_index_to_position(const int &index, const nav_msgs::OccupancyGrid &grid)
{
    int x = index % grid.info.width;
    int y = index / grid.info.width;

    return grid_xy_to_position(x, y, grid);
}

pcl::PointXYZ grid_xy_to_pointcloud_xyz(const int &x, const int &y, const nav_msgs::OccupancyGrid &grid)
{
    float real_x = grid.info.origin.position.x + (x + 0.5) * grid.info.resolution;
    float real_y = grid.info.origin.position.y + (y + 0.5) * grid.info.resolution;

    return pcl::PointXYZ(real_x, real_y, 0.0f);
}

pcl::PointXYZ grid_index_to_pointcloud_xyz(const int &index, const nav_msgs::OccupancyGrid &grid)
{
    int x = index % grid.info.width;
    int y = index / grid.info.width;

    return grid_xy_to_pointcloud_xyz(x, y, grid);
}

pcl::PointXYZRGB grid_xy_to_pointcloud_xyzrgb(const int &x, const int &y, const nav_msgs::OccupancyGrid &grid)
{
    pcl::PointXYZRGB ret;

    float real_x = grid.info.origin.position.x + (x + 0.5) * grid.info.resolution;
    float real_y = grid.info.origin.position.y + (y + 0.5) * grid.info.resolution;

    ret.x = real_x;
    ret.y = real_y;

    return ret;
}

pcl::PointXYZRGB grid_index_to_pointcloud_xyzrgb(const int &index, const nav_msgs::OccupancyGrid &grid)
{
    int x = index % grid.info.width;
    int y = index / grid.info.width;

    return grid_xy_to_pointcloud_xyzrgb(x, y, grid);
}

int grid_xy_to_grid_index(const int &x, const int &y, const nav_msgs::OccupancyGrid &grid)
{
    return y * grid.info.width + x;
}

tuple<int, int> grid_index_to_grid_xy(const int &index, const nav_msgs::OccupancyGrid &grid)
{
    int x = index % grid.info.width;
    int y = index / grid.info.width;

    return {x, y};
}

tuple<int, int> position_to_grid_xy(const geometry_msgs::Point32 &p, const nav_msgs::OccupancyGrid &grid)
{
    int x = static_cast<int>((p.x - grid.info.origin.position.x) / grid.info.resolution);
    int y = static_cast<int>((p.y - grid.info.origin.position.y) / grid.info.resolution);

    return {x, y};
}

tuple<int, int> position_to_grid_xy(const octomap::point3d &p, const nav_msgs::OccupancyGrid &grid)
{
    return position_to_grid_xy(point_octomap_to_ros(p), grid);
}

tuple<int, int> position_to_grid_xy(const cv::Point2f &p, const nav_msgs::OccupancyGrid &grid)
{
    return position_to_grid_xy(point_cv_to_ros(p), grid);
}

tuple<int, int> position_to_grid_xy(const pcl::PointXYZ &p, const nav_msgs::OccupancyGrid &grid)
{
    return position_to_grid_xy(point_pcl_xyz_to_ros(p), grid);
}

tuple<int, int> position_to_grid_xy(const pcl::PointXYZRGB &p, const nav_msgs::OccupancyGrid &grid)
{
    return position_to_grid_xy(point_pcl_xyzrgb_to_ros(p), grid);
}

int position_to_grid_index(const geometry_msgs::Point32 &p, const nav_msgs::OccupancyGrid &grid)
{
    auto [x, y] = position_to_grid_xy(p, grid);

    auto index = y * grid.info.width + x;

    return max(0, static_cast<int>(min(static_cast<int>(y * grid.info.width + x), static_cast<int>(grid.data.size() - 1))));
}

int position_to_grid_index(const octomap::point3d &p, const nav_msgs::OccupancyGrid &grid)
{
    return position_to_grid_index(point_octomap_to_ros(p), grid);
}

int position_to_grid_index(const cv::Point2f &p, const nav_msgs::OccupancyGrid &grid)
{
    return position_to_grid_index(point_cv_to_ros(p), grid);
}

obstacle_line create_line(const geometry_msgs::Point32 &p0, const geometry_msgs::Point32 &p1)
{
    obstacle_line ret;

    ret.p0 = p0;
    ret.p1 = p1;

    return ret;
}

obstacle_line create_line(const float &x0, const float &y0, const float &x1, const float &y1)
{
    return create_line(create_point(x0, y0), create_point(x1, y1));
}

obstacle_line create_line(const geometry_msgs::Point &p0, const geometry_msgs::Point &p1)
{
    return create_line(p0.x, p0.y, p1.x, p1.y);
}

obstacle_description create_obstacle(const geometry_msgs::Point32 &pos, const float &radius)
{
    obstacle_description ret;

    boost::uuids::uuid uuid = uuid_generator();
    ret.uuid = boost::uuids::to_string(uuid);
    ret.type = obstacle_type::CIRCLE;
    ret.center = pos;
    ret.radius = radius;

    return ret;
}

obstacle_description create_obstacle(const vector<obstacle_line> &boundaries)
{
    obstacle_description ret;

    boost::uuids::uuid uuid = uuid_generator();
    ret.uuid = boost::uuids::to_string(uuid);
    ret.type = obstacle_type::CONVEX;
    ret.boundaries = boundaries;

    // 计算重心
    float area = 0;
    float Cx = 0;
    float Cy = 0;
    size_t N = ret.boundaries.size();

    for (size_t i = 0; i < N; i++)
    {
        auto p0 = ret.boundaries[i].p0;
        auto p1 = ret.boundaries[(i + 1) % N].p0;

        float a = p0.x * p1.y - p1.x * p0.y;
        area += a;
        Cx += (p0.x + p1.x) * a;
        Cy += (p0.y + p1.y) * a;
    }

    if (area != 0)
    {
        area /= 2.0;
        Cx /= (6.0 * area);
        Cy /= (6.0 * area);
        ret.center = create_point(Cx, Cy);
    }

    return ret;
}

float min_distance_to_line(const geometry_msgs::Point32 &p, const obstacle_line &line)
{
    float line_length = sqrt(pow(line.p1.x - line.p0.x, 2) + pow(line.p1.y - line.p0.y, 2));

    if (line_length == 0)
    {
        return sqrt(pow(p.x - line.p0.x, 2) + pow(p.y - line.p0.y, 2));
    }

    float t = ((p.x - line.p0.x) * (line.p1.x - line.p0.x) + (p.y - line.p0.y) * (line.p1.y - line.p0.y)) / pow(line_length, 2);

    t = max(0.0f, min(1.0f, t));

    geometry_msgs::Point32 projection = create_point(line.p0.x + t * (line.p1.x - line.p0.x),
                                                     line.p0.y + t * (line.p1.y - line.p0.y));

    return sqrt(pow(p.x - projection.x, 2) + pow(p.y - projection.y, 2));
}

bool is_line_in_or_cross_circle(const geometry_msgs::Point32 &pos, const float &radius, const obstacle_line &line)
{
    return min_distance_to_line(pos, line) < radius;
}

bool is_obstacle_in_roi(const geometry_msgs::Point32 &pos, const float &radius, const obstacle_description &obstacle)
{
    if (obstacle.type == obstacle_type::CONVEX)
    {
        for (const auto &line : obstacle.boundaries)
        {
            if (is_line_in_or_cross_circle(pos, radius, line))
            {
                return true;
            }
        }
    }
    else if (obstacle.type == obstacle_type::CIRCLE)
    {
        float dist = sqrt(pow(pos.x - obstacle.center.x, 2) + pow(pos.y - obstacle.center.y, 2));

        return dist < (radius + obstacle.radius);
    }

    return false;
}

vector<obstacle_description> get_obstacles_in_roi(const geometry_msgs::Point32 &pos, const float &radius, const vector<obstacle_description> &obstacles)
{
    vector<obstacle_description> obstacles_in_roi;

    for (const auto &obstacle : obstacles)
    {
        if (is_obstacle_in_roi(pos, radius, obstacle))
        {
            obstacles_in_roi.push_back(obstacle);
        }
    }

    return obstacles_in_roi;
}

bool is_point_in_circle(const geometry_msgs::Point32 &center, const float &radius, const geometry_msgs::Point32 &p)
{
    return calculate_distance(p, center) <= radius;
}

tuple<geometry_msgs::Point32, float> circle_from_two_points(const geometry_msgs::Point32 &p1, const geometry_msgs::Point32 &p2)
{
    geometry_msgs::Point32 center;

    center.x = (p1.x + p2.x) / 2;
    center.y = (p1.y + p2.y) / 2;

    float radius = calculate_distance(p1, center);

    return {center, radius};
}

tuple<geometry_msgs::Point32, float> circle_from_three_points(const geometry_msgs::Point32 &p1, const geometry_msgs::Point32 &p2, const geometry_msgs::Point32 &p3)
{
    float d = 2 * (p1.x * (p2.y - p3.y) + p2.x * (p3.y - p1.y) + p3.x * (p1.y - p2.y));

    geometry_msgs::Point32 center;

    center.x = ((p1.x * p1.x + p1.y * p1.y) * (p2.y - p3.y) + (p2.x * p2.x + p2.y * p2.y) * (p3.y - p1.y) + (p3.x * p3.x + p3.y * p3.y) * (p1.y - p2.y)) / d;
    center.y = ((p1.x * p1.x + p1.y * p1.y) * (p3.x - p2.x) + (p2.x * p2.x + p2.y * p2.y) * (p1.x - p3.x) + (p3.x * p3.x + p3.y * p3.y) * (p2.x - p1.x)) / d;

    float radius = calculate_distance(p1, center);

    return {center, radius};
}

tuple<geometry_msgs::Point32, float> welzl(vector<geometry_msgs::Point32> points, vector<geometry_msgs::Point32> points_recurs, size_t n)
{
    if (n == 0 || points_recurs.size() == 3)
    {
        switch (points_recurs.size())
        {
        case 0:
            return {geometry_msgs::Point32(), 0};
        case 1:
            return {points_recurs[0], 0};
        case 2:
            return circle_from_two_points(points_recurs[0], points_recurs[1]);
        case 3:
            return circle_from_three_points(points_recurs[0], points_recurs[1], points_recurs[2]);
        }
    }

    size_t idx = rand() % n;
    geometry_msgs::Point32 p = points[idx];
    swap(points[idx], points[n - 1]);

    auto [circle_center, circle_radius] = welzl(points, points_recurs, n - 1);

    if (is_point_in_circle(circle_center, circle_radius, p))
    {
        return {circle_center, circle_radius};
    }

    points_recurs.push_back(p);

    return welzl(points, points_recurs, n - 1);
}

tuple<geometry_msgs::Point32, float> find_min_bounding_circle(const vector<geometry_msgs::Point32> &points)
{
    vector<geometry_msgs::Point32> points_modifiable = points;
    vector<geometry_msgs::Point32> points_recurs;

    return welzl(points_modifiable, points_recurs, points.size());
}

tuple<geometry_msgs::Point32, float> find_min_bounding_circle(const pcl::PointCloud<pcl::PointXYZ> &points)
{
    vector<geometry_msgs::Point32> ros_points;

    for (const auto &point : points)
    {
        ros_points.push_back(point_pcl_xyz_to_ros(point));
    }

    return find_min_bounding_circle(ros_points);
}

tuple<geometry_msgs::Point32, float> find_min_bounding_circle(const pcl::PointCloud<pcl::PointXYZRGB> &points)
{
    vector<geometry_msgs::Point32> ros_points;

    for (const auto &point : points)
    {
        ros_points.push_back(point_pcl_xyzrgb_to_ros(point));
    }

    return find_min_bounding_circle(ros_points);
}

float min_dist_between_obstacles(const obstacle_description &ob1, const obstacle_description &ob2)
{
    if (ob1.type == obstacle_type::CONVEX && ob2.type == obstacle_type::CONVEX)
    {
        if (is_obstacle_intersect(ob1, ob2) ||
            is_obstacle_in_obstacle(ob1, ob2) ||
            is_obstacle_in_obstacle(ob2, ob1))
        {
            return 0;
        }

        float min_dist = numeric_limits<float>::max();

        for (const auto &line2 : ob2.boundaries)
        {
            for (const auto &line1 : ob1.boundaries)
            {
                float dist_to_line = min_distance_to_line(line1.p0, line2);
                min_dist = min(min_dist, dist_to_line);
                dist_to_line = min_distance_to_line(line1.p1, line2);
                min_dist = min(min_dist, dist_to_line);
            }
        }

        for (const auto &line1 : ob1.boundaries)
        {
            for (const auto &line2 : ob2.boundaries)
            {
                float dist_to_line = min_distance_to_line(line2.p0, line1);
                min_dist = min(min_dist, dist_to_line);
                dist_to_line = min_distance_to_line(line2.p1, line1);
                min_dist = min(min_dist, dist_to_line);
            }
        }

        return min_dist;
    }
    else if (ob1.type == obstacle_type::CIRCLE && ob2.type == obstacle_type::CIRCLE)
    {
        float min_dist = calculate_distance(ob1.center, ob2.center) - ob1.radius - ob2.radius;

        min_dist = min_dist < 0 ? 0 : min_dist;

        return min_dist;
    }
    else
    {
        // 暂时不支持
        return -1;
    }
}

vector<geometry_msgs::PoseStamped> calc_path_orientation(const vector<geometry_msgs::PoseStamped> &path)
{
    vector<geometry_msgs::PoseStamped> ret;

    // 计算路径上每个点的近似切线角度
    size_t size = path.size();

    ret.resize(size);

#pragma omp parallel for
    for (int i = 0; i < size; i++)
    {
        ret[i].header = path[i].header;

        // 赋值点坐标
        ret[i].pose = path[i].pose;

        // 往前计算
        if (i < size - 2)
        {
            vector<geometry_msgs::Pose> forward_points;

            forward_points.clear();

            for (int j = 1; j <= min(5, (int)(size - i - 2)); j += 1)
            {
                forward_points.push_back(path[i + j].pose);
            }

            ret[i].pose.orientation =
                tf::createQuaternionMsgFromYaw(
                    calc_path_point_orientation(ret[i].pose, forward_points));
        }
        else if (i != size - 1)
        {
            ret[i].pose.orientation = ret[i - 1].pose.orientation;
        }
    }

    return ret;
}

vector<int> enumerate_line_indices(const float &x0, const float &y0, const float &x1, const float &y1,
                                   const int &width, const int &height, const float &resolu)
{
    int i0 = floor(x0 / resolu);
    int j0 = floor(y0 / resolu);
    int i1 = floor(x1 / resolu);
    int j1 = floor(y1 / resolu);

    vector<int> indices;

    int dx = abs(i1 - i0), dy = abs(j1 - j0);
    int sx = (i0 < i1) ? 1 : -1;
    int sy = (j0 < j1) ? 1 : -1;
    int err = dx - dy;

    int x = i0, y = j0;

    while (true)
    {
        if (x >= 0 && x < width && y >= 0 && y < height)
        {
            int index = y * width + x;

            if (index >= 0)
            {
                indices.push_back(index);
            }
        }

        if (x == i1 && y == j1)
        {
            break;
        }

        int e2 = 2 * err;

        if (e2 > -dy)
        {
            err -= dy;
            x += sx;
        }

        if (e2 < dx)
        {
            err += dx;
            y += sy;
        }
    }

    return indices;
}

vector<int> enumerate_line_indices(
    const geometry_msgs::Point32 &p0,
    const geometry_msgs::Point32 &p1,
    const nav_msgs::OccupancyGrid &grid)
{
    const float resolution = grid.info.resolution;
    const float origin_x = grid.info.origin.position.x;
    const float origin_y = grid.info.origin.position.y;
    const int width = grid.info.width;
    const int height = grid.info.height;

    int x0 = static_cast<int>(floor((p0.x - origin_x) / resolution));
    int y0 = static_cast<int>(floor((p0.y - origin_y) / resolution));
    int x1 = static_cast<int>(floor((p1.x - origin_x) / resolution));
    int y1 = static_cast<int>(floor((p1.y - origin_y) / resolution));

    int dx = abs(x1 - x0);
    int dy = abs(y1 - y0);
    int sx = (x0 < x1) ? 1 : -1;
    int sy = (y0 < y1) ? 1 : -1;
    int err = dx - dy;

    vector<int> indices;
    indices.reserve(max(dx, dy) + 1);

    int x = x0;
    int y = y0;

    while (true)
    {
        if (x >= 0 && x < width && y >= 0 && y < height)
        {
            int index = y * width + x;

            indices.push_back(index);
        }

        if (x == x1 && y == y1)
            break;

        int e2 = 2 * err;

        if (e2 > -dy)
        {
            err -= dy;
            x += sx;
        }

        if (e2 < dx)
        {
            err += dx;
            y += sy;
        }
    }

    return indices;
}

bool is_segment_no_collision(const float &x0, const float &y0, const float &x1, const float &y1, const int &step,
                             const int &width, const int &height, const float &resolu,
                             const float &min_obs_dist,
                             const vector<float> &obs_dist_table)
{
    auto grid_indices = enumerate_line_indices(x0, y0, x1, y1, width, height, resolu);

    size_t grid_indices_size = grid_indices.size();

    for (int i = 0;; i += step)
    {
        if (i >= grid_indices_size - 1)
        {
            i = grid_indices_size - 1;
        }

        int grid_index = grid_indices[i];

        if (grid_index >= 0 && grid_index < obs_dist_table.size())
        {
            if (obs_dist_table[grid_index] < min_obs_dist)
            {
                return false;
            }
        }

        if (i >= grid_indices_size - 1)
        {
            break;
        }
    }

    return true;
}

exploration_segment_type exploration_check_segment_type(const geometry_msgs::Point32 &p0, const geometry_msgs::Point32 &p1, const int &step,
                                                        const float &min_obs_dist,
                                                        const nav_msgs::OccupancyGrid &grid,
                                                        const vector<float> &obs_dist_table,
                                                        const bool &check_obs,
                                                        const int &free_threshold, const int &occupied_threshold)
{
    auto grid_indices = enumerate_line_indices(p0, p1, grid);

    size_t grid_indices_size = grid_indices.size();

    bool unknow_flag = false;

    for (int i = 0;; i += step)
    {
        if (i >= grid_indices_size - 1)
        {
            i = grid_indices_size - 1;
        }

        int grid_index = grid_indices[i];

        if (grid_index >= 0 && grid_index < obs_dist_table.size())
        {
            if (check_obs)
            {
                if (obs_dist_table[grid_index] <= min_obs_dist)
                {
                    return exploration_segment_type::WITH_COLLISION;
                }
            }

            if (grid.data[grid_index] < 0 ||
                (grid.data[grid_index] > free_threshold && grid.data[grid_index] < occupied_threshold))
            {
                unknow_flag = true;
            }
        }
        else
        {
            unknow_flag = true;
        }

        if (i >= grid_indices_size - 1)
        {
            break;
        }
    }

    return unknow_flag ? exploration_segment_type::NO_COLLISION_WITH_UNKNOW : exploration_segment_type::NO_COLLISION;
}

nav_msgs::OccupancyGrid clear_footprint_on_grid(const nav_msgs::OccupancyGrid &grid,
                                                const geometry_msgs::Point32 &origin, const float &radius)
{
    nav_msgs::OccupancyGrid ret = grid;

    size_t size = ret.data.size();

#pragma omp parallel for
    for (int i = 0; i < size; i++)
    {
        if (calculate_distance(grid_index_to_position(i, ret), origin) <= radius + 0.01)
        {
            ret.data[i] = 0;
        }
    }

    return ret;
}

vector<float> calc_min_dist_to_obs_table(const nav_msgs::OccupancyGrid &grid, const int &threshold)
{
    int width = grid.info.width;
    int height = grid.info.height;
    float resolution = grid.info.resolution;

    pcl::PointCloud<pcl::PointXY>::Ptr occupied_points(new pcl::PointCloud<pcl::PointXY>());
    vector<pcl::PointXY, Eigen::aligned_allocator<pcl::PointXY>> temp_points;

#pragma omp parallel
    {
        vector<pcl::PointXY> local_points;

#pragma omp for nowait collapse(2)
        for (int y = 0; y < height; y++)
        {
            for (int x = 0; x < width; x++)
            {
                int index = y * width + x;

                if (grid.data[index] >= threshold)
                {
                    pcl::PointXY point;
                    point.x = x * resolution;
                    point.y = y * resolution;
                    local_points.push_back(point);
                }
            }
        }

#pragma omp critical
        temp_points.insert(temp_points.end(), local_points.begin(), local_points.end());
    }

    occupied_points->points = move(temp_points);

    if (occupied_points->points.empty())
    {
        return vector<float>(width * height, numeric_limits<float>::max());
    }

    pcl::KdTreeFLANN<pcl::PointXY> kdtree;
    kdtree.setInputCloud(occupied_points);

    vector<float> min_dist_table(width * height, 0.0f);

#pragma omp parallel for collapse(2) schedule(dynamic)
    for (int y = 0; y < height; y++)
    {
        for (int x = 0; x < width; x++)
        {
            int index = y * width + x;

            if (grid.data[index] >= threshold)
            {
                min_dist_table[index] = 0.0f;
            }
            else
            {
                pcl::PointXY query_point;
                query_point.x = x * resolution;
                query_point.y = y * resolution;

                vector<int> point_idx_nkn_search(1);
                vector<float> point_squared_distance(1);

                if (kdtree.nearestKSearch(query_point, 1, point_idx_nkn_search, point_squared_distance) > 0)
                {
                    min_dist_table[index] = sqrt(point_squared_distance[0]);
                }
                else
                {
                    min_dist_table[index] = numeric_limits<float>::max();
                }
            }
        }
    }

    return min_dist_table;
}

vector<float> calc_min_dist_to_obs_table(const nav_msgs::OccupancyGrid &grid,
                                         const float center_x, const float center_y, const float radius,
                                         const int &threshold)
{
    const int width = grid.info.width;
    const int height = grid.info.height;
    const float resolution = grid.info.resolution;
    const float origin_x = grid.info.origin.position.x;
    const float origin_y = grid.info.origin.position.y;

    pcl::PointCloud<pcl::PointXY>::Ptr occupied_points(new pcl::PointCloud<pcl::PointXY>());
    vector<pcl::PointXY, Eigen::aligned_allocator<pcl::PointXY>> temp_points;

#pragma omp parallel
    {
        vector<pcl::PointXY> local_points;
        const pcl::PointXY center{center_x, center_y};

#pragma omp for collapse(2) nowait
        for (int y = 0; y < height; y++)
        {
            for (int x = 0; x < width; x++)
            {
                int index = y * width + x;

                if (grid.data[index] >= threshold)
                {
                    pcl::PointXY point;
                    point.x = x * resolution + origin_x;
                    point.y = y * resolution + origin_y;

                    if (calculate_distance(point, center) <= radius)
                    {
                        local_points.push_back(point);
                    }
                }
            }
        }

#pragma omp critical
        temp_points.insert(temp_points.end(), local_points.begin(), local_points.end());
    }

    if (temp_points.empty())
    {
        return vector<float>(width * height, numeric_limits<float>::max());
    }

    occupied_points->points = move(temp_points);

    pcl::KdTreeFLANN<pcl::PointXY> kdtree;
    kdtree.setInputCloud(occupied_points);

    vector<float> min_dist_table(width * height, 0.0f);

    const pcl::PointXY center{center_x, center_y};

#pragma omp parallel for collapse(2) schedule(dynamic)
    for (int y = 0; y < height; y++)
    {
        for (int x = 0; x < width; x++)
        {
            int index = y * width + x;

            if (grid.data[index] >= threshold)
            {
                min_dist_table[index] = 0.0f;
                continue;
            }

            pcl::PointXY query_point;
            query_point.x = x * resolution + origin_x;
            query_point.y = y * resolution + origin_y;

            if (calculate_distance(query_point, center) > radius)
            {
                min_dist_table[index] = numeric_limits<float>::max();
                continue;
            }

            vector<int> point_idx(1);
            vector<float> point_squared_dist(1);

            if (kdtree.nearestKSearch(query_point, 1, point_idx, point_squared_dist) > 0)
            {
                min_dist_table[index] = sqrt(point_squared_dist[0]);
            }
            else
            {
                min_dist_table[index] = numeric_limits<float>::max();
            }
        }
    }

    return min_dist_table;
}

vector<int> resample_points(const vector<geometry_msgs::Point32> &points, const vector<int> &indices,
                            const float &min_dist)
{
    if (points.empty() || indices.empty())
    {
        return {};
    }

    pcl::PointCloud<pcl::PointXYZL>::Ptr cloud(new pcl::PointCloud<pcl::PointXYZL>());

    size_t size = points.size();

    for (int i = 0; i < size; i++)
    {
        pcl::PointXYZL pcl_point;
        pcl_point.x = points[i].x;
        pcl_point.y = points[i].y;
        pcl_point.label = indices[i];
        cloud->points.push_back(pcl_point);
    }

    pcl::PointCloud<pcl::PointXYZL>::Ptr filtered_cloud(new pcl::PointCloud<pcl::PointXYZL>());
    pcl::VoxelGrid<pcl::PointXYZL> voxel_filter;
    voxel_filter.setInputCloud(cloud);
    voxel_filter.setLeafSize(min_dist, min_dist, 0.1f);
    voxel_filter.filter(*filtered_cloud);

    vector<int> resampled_point_indices;

    for (const auto &pcl_point : filtered_cloud->points)
    {
        resampled_point_indices.push_back(pcl_point.label);
    }

    if (resampled_point_indices.empty())
    {
        resampled_point_indices.push_back(indices[0]);
    }

    return resampled_point_indices;
}

vector<geometry_msgs::Point32> resample_points(const vector<geometry_msgs::Point32> &points, const float &min_dist)
{
    if (points.empty())
    {
        return {};
    }

    pcl::PointCloud<pcl::PointXYZ>::Ptr cloud(new pcl::PointCloud<pcl::PointXYZ>());

    size_t size = points.size();

    for (int i = 0; i < size; i++)
    {
        pcl::PointXYZ pcl_point;
        pcl_point.x = points[i].x;
        pcl_point.y = points[i].y;
        cloud->points.push_back(pcl_point);
    }

    pcl::PointCloud<pcl::PointXYZ>::Ptr filtered_cloud(new pcl::PointCloud<pcl::PointXYZ>());
    pcl::VoxelGrid<pcl::PointXYZ> voxel_filter;
    voxel_filter.setInputCloud(cloud);
    voxel_filter.setLeafSize(min_dist, min_dist, 1.0f);
    voxel_filter.filter(*filtered_cloud);

    vector<geometry_msgs::Point32> resampled_points;

    for (const auto &pcl_point : filtered_cloud->points)
    {
        geometry_msgs::Point32 point;
        point.x = pcl_point.x;
        point.y = pcl_point.y;
        resampled_points.push_back(point);
    }

    if (resampled_points.empty())
    {
        resampled_points.push_back(points[0]);
    }

    return resampled_points;
}

geometry_msgs::Point32 generate_point(const geometry_msgs::Point32 &p0, const geometry_msgs::Point32 &dir, const float &dist)
{
    geometry_msgs::Point32 new_point;

    if (calculate_distance(p0, dir) <= dist)
    {
        new_point = dir;

        return new_point;
    }

    float magnitude = sqrt(dir.x * dir.x + dir.y * dir.y + dir.z * dir.z);

    if (magnitude <= 1e-8)
    {
        new_point.x = p0.x;
        new_point.y = p0.y + dist;
        new_point.z = p0.z;
    }
    else
    {
        geometry_msgs::Point32 normalized_dir;
        normalized_dir.x = dir.x / magnitude;
        normalized_dir.y = dir.y / magnitude;
        normalized_dir.z = dir.z / magnitude;

        new_point.x = p0.x + normalized_dir.x * dist;
        new_point.y = p0.y + normalized_dir.y * dist;
        new_point.z = p0.z + normalized_dir.z * dist;
    }

    return new_point;
}

geometry_msgs::Point32 generate_point_on_segment(const geometry_msgs::Point32 &p0, const geometry_msgs::Point32 &dir, const float &dist)
{
    geometry_msgs::Point32 new_point;

    float magnitude = sqrt(dir.x * dir.x + dir.y * dir.y + dir.z * dir.z);

    if (magnitude <= 1e-8)
    {
        new_point = p0;
    }
    else
    {
        geometry_msgs::Point32 normalized_dir;
        normalized_dir.x = dir.x / magnitude;
        normalized_dir.y = dir.y / magnitude;
        normalized_dir.z = dir.z / magnitude;

        new_point.x = p0.x + normalized_dir.x * dist;
        new_point.y = p0.y + normalized_dir.y * dist;
        new_point.z = p0.z + normalized_dir.z * dist;
    }

    return new_point;
}

float calc_unknow_area(const geometry_msgs::Point32 &p, const float &radius, const nav_msgs::OccupancyGrid &grid,
                       const int &free_threshold, const int &occupied_threshold)
{
    float resolution = grid.info.resolution;
    float origin_x = grid.info.origin.position.x;
    float origin_y = grid.info.origin.position.y;
    int width = grid.info.width;
    int height = grid.info.height;

    int center_x = static_cast<int>((p.x - origin_x) / resolution);
    int center_y = static_cast<int>((p.y - origin_y) / resolution);
    int radius_in_cells = static_cast<int>(radius / resolution);

    int unknown_count = 0;

    for (int y = -radius_in_cells; y <= radius_in_cells; y++)
    {
        for (int x = -radius_in_cells; x <= radius_in_cells; x++)
        {
            int grid_x = center_x + x;
            int grid_y = center_y + y;

            if (x * x + y * y <= radius_in_cells * radius_in_cells)
            {
                if (grid_x >= 0 && grid_x < width && grid_y >= 0 && grid_y < height)
                {
                    int index = grid_y * width + grid_x;

                    if (index >= 0 && index < grid.data.size())
                    {
                        if (grid.data[index] < 0 || (grid.data[index] > free_threshold && grid.data[index] < occupied_threshold))
                        {
                            unknown_count++;
                        }
                    }
                }
            }
        }
    }

    float unknown_area = unknown_count * resolution * resolution;

    return unknown_area;
}

tuple<int, geometry_msgs::Point32> get_nearest_point(const geometry_msgs::Point32 &p,
                                                     const vector<geometry_msgs::Point32> &points, const vector<int> &indices)
{
    int index = -1;
    geometry_msgs::Point32 nearest_point;
    float min_dist = INFINITY;

    size_t size = points.size();

    for (int i = 0; i < size; i++)
    {
        float dist = calculate_distance(p, points[i]);

        if (dist < min_dist && dist > 1e-8)
        {
            index = indices[i];
            min_dist = dist;
            nearest_point.x = points[i].x;
            nearest_point.y = points[i].y;
            nearest_point.z = points[i].z;
        }
    }

    return {index, nearest_point};
}

tuple<int, geometry_msgs::Point32> get_nearest_point(const geometry_msgs::Point32 &p,
                                                     const vector<geometry_msgs::Point32> &points, const vector<int> &indices, const vector<bool> &del_states)
{
    int index = -1;
    geometry_msgs::Point32 nearest_point;
    float min_dist = INFINITY;

    size_t size = points.size();

    for (int i = 0; i < size; i++)
    {
        if (del_states[i])
        {
            continue;
        }

        float dist = calculate_distance(p, points[i]);

        if (dist < min_dist && dist > 1e-8)
        {
            index = indices[i];
            min_dist = dist;
            nearest_point.x = points[i].x;
            nearest_point.y = points[i].y;
            nearest_point.z = points[i].z;
        }
    }

    return {index, nearest_point};
}

bool is_point_in_map(const geometry_msgs::Point32 &p, const nav_msgs::OccupancyGrid &grid)
{
    auto [x, y] = position_to_grid_xy(p, grid);

    if (x < 0 || x >= grid.info.width || y < 0 || y >= grid.info.height)
    {
        return false;
    }

    auto index = y * grid.info.width + x;

    return index >= 0 && index < static_cast<int>(grid.data.size());
}

bool is_point_unknow(const geometry_msgs::Point32 &p, const nav_msgs::OccupancyGrid &grid,
                     const int &free_threshold, const int &occupied_threshold)
{
    auto index = position_to_grid_index(p, grid);

    if (free_threshold < 0 || occupied_threshold < 0)
    {
        return grid.data[index] < 0;
    }

    return grid.data[index] < 0 || (grid.data[index] > free_threshold && grid.data[index] < occupied_threshold);
}

float calc_decayed_distance(const geometry_msgs::Point32 &p, const nav_msgs::OccupancyGrid &grid, const vector<float> &obs_dist_table,
                            const float &min_dist_to_obs, const float &min_expand_dist, const float &max_expand_dist)
{
    float ret = max_expand_dist;

    int index = position_to_grid_index(p, grid);

    if (index >= 0 && index < obs_dist_table.size() && grid.data.size() == obs_dist_table.size())
    {
        float dist = obs_dist_table[index];

        if (dist >= min_dist_to_obs && dist <= 2.0f * min_dist_to_obs)
        {
            float t = (dist - min_dist_to_obs) / (min_dist_to_obs);
            ret = min_expand_dist + t * (max_expand_dist - min_expand_dist);
        }
        else if (dist > 2.0f * min_dist_to_obs)
        {
            ret = max_expand_dist;
        }
    }

    return ret;
}

float calc_orientation_diff(const geometry_msgs::Point32 &p0, const geometry_msgs::Point32 &p1, const geometry_msgs::Point32 &p2)
{
    float dx1 = p1.x - p0.x;
    float dy1 = p1.y - p0.y;
    float dx2 = p2.x - p1.x;
    float dy2 = p2.y - p1.y;

    float mag1 = sqrt(dx1 * dx1 + dy1 * dy1);
    float mag2 = sqrt(dx2 * dx2 + dy2 * dy2);

    if (mag1 < 1e-8 || mag2 < 1e-8)
    {
        return 0.0f;
    }

    dx1 /= mag1;
    dy1 /= mag1;
    dx2 /= mag2;
    dy2 /= mag2;

    float dot_product = dx1 * dx2 + dy1 * dy2;
    float cross_product = dx1 * dy2 - dy1 * dx2;

    float angle_diff = atan2(cross_product, dot_product);

    return abs(angle_diff);
}

float calc_coverage_rate(const vector<geometry_msgs::Point32> &points, const float &sensing_radius)
{
    float ret = 0.0f;

    auto circle = find_min_bounding_circle(points);

    float sensing_area = M_PI * pow(sensing_radius, 2);

    if (sensing_area > 0)
    {
        ret = (M_PI * pow(get<1>(circle), 2)) / sensing_area;
    }

    ret = ret < 0.0f ? 0.0f : (ret > 1.0f ? 1.0f : ret);

    return ret;
}

float calc_coverage_density(const vector<geometry_msgs::Point32> &points, const vector<geometry_msgs::Point32> &prev_points)
{
    float ret = 0.0f;

    if (points.empty() || points.size() != prev_points.size())
    {
        return ret;
    }

    pcl::PointCloud<pcl::PointXY>::Ptr cloud(new pcl::PointCloud<pcl::PointXY>());

    for (const auto &point : points)
    {
        pcl::PointXY pcl_point;
        pcl_point.x = point.x;
        pcl_point.y = point.y;
        cloud->points.push_back(pcl_point);
    }

    pcl::KdTreeFLANN<pcl::PointXY> kdtree;
    kdtree.setInputCloud(cloud);

    size_t size = points.size();

    int counter = 0;
    float ratio_sum = 0;

#pragma omp parallel for reduction(+ : ratio_sum, counter)
    for (int i = 0; i < size; i++)
    {
        float expand_dist = calculate_distance(points[i], prev_points[i]);

        vector<int> nearest_indices(2);
        vector<float> nearest_distances(2);

        if (kdtree.nearestKSearch(cloud->points[i], 2, nearest_indices, nearest_distances) > 1)
        {
            float min_dist = sqrt(nearest_distances[1]);

            if (min_dist > numeric_limits<float>::epsilon())
            {
                ratio_sum += expand_dist / min_dist;

                counter++;
            }
        }
    }

    if (counter > 0)
    {
        ret = ratio_sum / (float)counter;
    }

    return ret;
}

tuple<float, float> get_grid_max_min(const nav_msgs::OccupancyGrid &grid)
{
    float max_value = numeric_limits<float>::lowest();
    float min_value = numeric_limits<float>::max();

    for (const auto &value : grid.data)
    {
        if (value >= 254 || value <= 0)
        {
            continue;
        }

        if (value > max_value)
        {
            max_value = value;
        }
        if (value < min_value)
        {
            min_value = value;
        }
    }

    if (max_value == numeric_limits<float>::lowest() ||
        min_value == numeric_limits<float>::max())
    {
        return make_tuple(-1.0f, -1.0f);
    }

    return make_tuple(max_value, min_value);
}

vector<geometry_msgs::Point32> get_round_points(const geometry_msgs::Point32 &p,
                                                const float &radius, const int &num,
                                                const nav_msgs::OccupancyGrid &grid,
                                                const float &min_obs_dist, const vector<float> &obs_dist_table)
{
    vector<geometry_msgs::Point32> points;
    points.reserve(num + 1);

    points.push_back(p);

    for (int i = 0; i < num; i++)
    {
        double theta = 2.0 * M_PI * i / num;

        geometry_msgs::Point32 pt;

        pt.x = p.x + radius * cos(theta);
        pt.y = p.y + radius * sin(theta);
        pt.z = p.z;

        int index = position_to_grid_index(pt, grid);

        if (index >= 0 && index < grid.data.size())
        {
            if (obs_dist_table[index] >= min_obs_dist + 0.03)
            {
                points.push_back(pt);
            }
        }
    }

    return points;
}

vector<geometry_msgs::PoseStamped> get_round_points(const geometry_msgs::PoseStamped &p,
                                                    const float &radius, const int &num,
                                                    const nav_msgs::OccupancyGrid &grid,
                                                    const float &min_obs_dist, const vector<float> &obs_dist_table)
{
    vector<geometry_msgs::PoseStamped> points;
    points.reserve(num);

    geometry_msgs::Point32 p1;
    p1.x = p.pose.position.x;
    p1.y = p.pose.position.y;
    p1.z = p.pose.position.z;

    auto result = get_round_points(p1, radius, num, grid, min_obs_dist, obs_dist_table);

    size_t size = result.size();

    for (int i = 0; i < size; i++)
    {
        geometry_msgs::PoseStamped pose = p;
        pose.pose.position.x = result[i].x;
        pose.pose.position.y = result[i].y;
        pose.pose.position.z = result[i].z;

        points.push_back(pose);
    }

    return points;
}

float calc_seg_direction(const geometry_msgs::PoseStamped &p0, const geometry_msgs::Point32 &p1)
{
    float dx = p1.x - p0.pose.position.x;
    float dy = p1.y - p0.pose.position.y;

    float direction = atan2(dy, dx);

    return direction;
}

float calc_map_area(const nav_msgs::OccupancyGrid &grid,
                    const int &free_threshold, const int &occupied_threshold)
{
    const double cell_area = grid.info.resolution * grid.info.resolution;

    uint64_t valid_count = 0;
    const size_t n = grid.data.size();

#pragma omp parallel for reduction(+ : valid_count) schedule(static)
    for (size_t i = 0; i < n; i++)
    {
        int8_t v = grid.data[i];

        if (v >= 0 && (v <= free_threshold || v >= occupied_threshold))
        {
            valid_count += 1;
        }
    }

    return static_cast<float>(valid_count * cell_area);
}