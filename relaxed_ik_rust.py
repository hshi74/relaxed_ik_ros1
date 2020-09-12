#! /usr/bin/env python

import cartesian_path
import ctypes
import numpy
import os
import rospkg
import rospy
import transformations as T
import yaml

from pykdl_utils.kdl_kinematics import KDLKinematics
from relaxed_ik_ros1.msg import EEPoseGoals, JointAngles
from std_msgs.msg import Float64
from timeit import default_timer as timer
from urdf_parser_py.urdf import URDF
from visualization_msgs.msg import InteractiveMarkerFeedback

class Opt(ctypes.Structure):
    _fields_ = [("data", ctypes.POINTER(ctypes.c_double)), ("length", ctypes.c_int)]

rospack = rospkg.RosPack()
p = rospack.get_path('relaxed_ik_ros1')
os.chdir(p + "/relaxed_ik_core")

lib = ctypes.cdll.LoadLibrary(p + '/relaxed_ik_core/target/debug/librelaxed_ik_lib.so')
lib.solve.restype = Opt

def dynObstacle_cb(msg):
    # update dynamic collision obstacles in relaxed IK
    pos_arr = (ctypes.c_double * 3)()
    quat_arr = (ctypes.c_double * 4)()

    pos_arr[0] = msg.pose.position.x
    pos_arr[1] = msg.pose.position.y
    pos_arr[2] = msg.pose.position.z

    quat_arr[0] = msg.pose.orientation.x
    quat_arr[1] = msg.pose.orientation.y
    quat_arr[2] = msg.pose.orientation.z
    quat_arr[3] = msg.pose.orientation.w

    lib.dynamic_obstacle_cb(msg.marker_name, pos_arr, quat_arr)

eepg = None
def eePoseGoals_cb(msg):
    global eepg
    eepg = msg

def main(args=None):
    global eepg

    print("\nSolver initialized!")

    rospy.init_node('relaxed_ik')

    rospy.Subscriber('/simple_marker/feedback', InteractiveMarkerFeedback, dynObstacle_cb)
    rospy.Subscriber('/relaxed_ik/ee_pose_goals', EEPoseGoals, eePoseGoals_cb)
    angles_pub = rospy.Publisher('/relaxed_ik/joint_angle_solutions', JointAngles, queue_size=3)

    robot = URDF.from_parameter_server()
    kdl_kin = KDLKinematics(robot, "/base", "/right_hand")

    path_to_src = os.path.dirname(__file__)
    info_file_name = open(path_to_src + '/relaxed_ik_core/config/loaded_robot', 'r').read()
    info_file_path = path_to_src + '/relaxed_ik_core/config/info_files/' + info_file_name
    info_file = open(info_file_path, 'r')
    y = yaml.load(info_file)
    starting_config = y['starting_config']

    pose = kdl_kin.forward(starting_config)
    init_trans = [pose[0,3], pose[1,3], pose[2,3]]
    init_rot = T.quaternion_from_matrix(pose)

    waypoints = cartesian_path.read_cartesian_path(rospkg.RosPack().get_path('relaxed_ik_ros1') + "/cartesian_path_files/cartesian_path_prototype")
    
    goal = waypoints[len(waypoints)-1]
    trans_rel_goal = [goal.position.x, goal.position.y, goal.position.z]
    rot_rel_goal = [goal.orientation.w, goal.orientation.x, goal.orientation.y, goal.orientation.z]
    trans_goal = numpy.array(init_trans) + numpy.array(trans_rel_goal)
    rot_goal = T.quaternion_multiply(rot_rel_goal, init_rot)
    print("Final goal position: {}\nFinal goal orientation: {}".format(list(trans_goal), list(rot_goal)))

    ja_stream = []
    index = 0
    # eef_step = 0.002
    # eef_last_trans = init_trans
    pos_goal_tolerance = 0.001
    quat_goal_tolerance = 0.001
    dis = numpy.linalg.norm(numpy.array(init_trans) - numpy.array(trans_goal))
    angle_between = numpy.linalg.norm(T.quaternion_disp(init_rot, rot_goal)) * 2.0
    while not (dis < pos_goal_tolerance and angle_between < quat_goal_tolerance and index == len(waypoints) - 1):
        p = waypoints[index]
        pos_arr = (ctypes.c_double * 3)()
        quat_arr = (ctypes.c_double * 4)()

        pos_arr[0] = p.position.x
        pos_arr[1] = p.position.y
        pos_arr[2] = p.position.z

        quat_arr[0] = p.orientation.x
        quat_arr[1] = p.orientation.y
        quat_arr[2] = p.orientation.z
        quat_arr[3] = p.orientation.w

        # start = timer()
        xopt = lib.solve(pos_arr, len(pos_arr), quat_arr, len(quat_arr))
        # end = timer()
        # print("Speed: {}".format(1.0 / (end - start)))

        ja_list = []
        for i in range(xopt.length):
            ja_list.append(xopt.data[i])
        
        # print(ja_list)
        ja_stream.append(ja_list)

        pose = kdl_kin.forward(ja_list)
        trans = [pose[0,3], pose[1,3], pose[2,3]]
        rot = T.quaternion_from_matrix(pose)
        # print(trans, rot)
        
        dis = numpy.linalg.norm(numpy.array(trans) - numpy.array(trans_goal))
        angle_between = numpy.linalg.norm(T.quaternion_disp(rot, rot_goal)) * 2.0
        # print(dis, angle_between)

        if index < len(waypoints) - 1: 
            index = index + 1

    # print(ja_stream)
    print("\nSize of the joint state stream: {}".format(len(ja_stream)))

    rate = rospy.Rate(300)
    index = 0
    while not rospy.is_shutdown():
        ja = JointAngles()
        ja.angles.data = ja_stream[index]
        angles_pub.publish(ja)
        if index < len(ja_stream) - 1:
            index = index + 1
        rate.sleep()

    # while eepg == None: continue

    # rate = rospy.Rate(3000)
    # while not rospy.is_shutdown():
    #     pose_goals = eepg.ee_poses
    #     header = eepg.header
    #     pos_arr = (ctypes.c_double * (3 * len(pose_goals)))()
    #     quat_arr = (ctypes.c_double * (4 * len(pose_goals)))()

    #     for i in range(len(pose_goals)):
    #         p = pose_goals[i]
    #         pos_arr[3*i] = p.position.x
    #         pos_arr[3*i+1] = p.position.y
    #         pos_arr[3*i+2] = p.position.z

    #         quat_arr[4*i] = p.orientation.x
    #         quat_arr[4*i+1] = p.orientation.y
    #         quat_arr[4*i+2] = p.orientation.z
    #         quat_arr[4*i+3] = p.orientation.w

    #     start = timer()
    #     xopt = lib.solve(pos_arr, len(pos_arr), quat_arr, len(quat_arr))
    #     end = timer()
    #     print("Speed: {}".format(1.0 / (end - start)))

    #     ja = JointAngles()
    #     ja.header = header
    #     ja_str = "["
    #     for i in range(xopt.length):
    #         ja.angles.data.append(xopt.data[i])
    #         ja_str += str(xopt.data[i])
    #         if i == xopt.length - 1:
    #             ja_str += "]"
    #         else: 
    #             ja_str += ", "

    #     angles_pub.publish(ja)
    #     # print(ja_str)

    #     rate.sleep()

if __name__ == '__main__':
    main()
