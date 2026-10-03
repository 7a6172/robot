#include <iostream>
#include <utils/global_planner/osqp_smoother.h>

bool osqp_smoother::solve(
	const std::vector<std::pair<double, double>> &raw_point2d,
	const std::vector<point_constraint_rect> &bounds, std::vector<double> *opt_x,
	std::vector<double> *opt_y)
{
	return op_with_osqp(raw_point2d, bounds, opt_x, opt_y);

	return true;
}

bool osqp_smoother::op_with_osqp(
	const std::vector<std::pair<double, double>> &raw_point2d,
	const std::vector<point_constraint_rect> &bounds, std::vector<double> *opt_x,
	std::vector<double> *opt_y)
{
	if (opt_x == nullptr || opt_y == nullptr)
	{
		std::cout << "opt_x or opt_y is nullptr" << std::endl;

		return false;
	}

	osqp_utils solver;

	solver.set_ref_points(raw_point2d);
	solver.set_bounds_around_refs(bounds);

	if (!solver.solve())
	{
		return false;
	}

	*opt_x = solver.opt_x();
	*opt_y = solver.opt_y();

	return true;
}