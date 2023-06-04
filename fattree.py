# Copyright (C) 2016 Huang MaChi at Chongqing University
# of Posts and Telecommunications, China.
# Copyright (C) 2016 Li Cheng at Beijing University of Posts
# and Telecommunications. www.muzixing.com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import random
from mininet.net import Mininet
from mininet.node import Controller, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel,info
from mininet.link import Link, Intf, TCLink
from mininet.topo import Topo
from subprocess import Popen
from multiprocessing import Process
import numpy as np
import os
import logging
import argparse
import time
import sys
import iperf_peers
import ele_jitter
parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,parentdir)
parser = argparse.ArgumentParser(description="Parameters importation")
parser.add_argument('--k', dest='k', type=int, default=4, choices=[4, 8], help="Switch fanout number")
parser.add_argument('--duration', dest='duration', type=int, default=60, help="Duration (sec) for each iperf traffic generation")
parser.add_argument('--dir', dest='output_dir', help="Directory to store outputs")
parser.add_argument('--cpu', dest='cpu', type=float, default=1.0, help='Total CPU to allocate to hosts')
args = parser.parse_args()
class Fattree(Topo):
	"""
		Class of Fattree Topology.
	"""
	CoreSwitchList = []
	AggSwitchList = []
	EdgeSwitchList = []
	HostList = []

	def __init__(self, k, density):
		self.pod = k
		self.density = density
		self.iCoreLayerSwitch = (k/2)**2
		self.iAggLayerSwitch = int(k*k/2)
		self.iEdgeLayerSwitch = int(k*k/2)
		self.iHost = self.iEdgeLayerSwitch * density

		# Topo initiation
		Topo.__init__(self)

	def createNodes(self):
		self.createCoreLayerSwitch(self.iCoreLayerSwitch)
		self.createAggLayerSwitch(self.iAggLayerSwitch)
		self.createEdgeLayerSwitch(self.iEdgeLayerSwitch)
		self.createHost(self.iHost)

	def _addSwitch(self, number, level, switch_list):
		"""
			Create switches.
		"""
		for i in range(1, int(number+1)):
			PREFIX = str(level) + "00"
			if i >= 10:
				PREFIX = str(level) + "0"
			switch_list.append(self.addSwitch(PREFIX + str(i)))

	def createCoreLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 1, self.CoreSwitchList)

	def createAggLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 2, self.AggSwitchList)

	def createEdgeLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 3, self.EdgeSwitchList)

	def createHost(self, NUMBER):
		"""
			Create hosts.
		"""
		for i in range(1, int(NUMBER+1)):
			if i >= 100:
				PREFIX = "h"
			elif i >= 10:
				PREFIX = "h0"
			else:
				PREFIX = "h00"
			self.HostList.append(self.addHost(PREFIX + str(i), cpu=args.cpu/float(NUMBER)))

	def createLinks(self, bw_c2a=100, bw_a2e=100, bw_e2h=100):
		"""
			Add network links.
		"""
		# Core to Agg
		end = int(self.pod/2)
		for x in range(0, self.iAggLayerSwitch, end):
			for i in range(0, end):
				for j in range(0, end):
					self.addLink(
						self.CoreSwitchList[i*end+j],
						self.AggSwitchList[x+i],
						bw=bw_c2a, cls=TCLink,max_queue_size=1000)   # use_htb=False

		# Agg to Edge
		for x in range(0, self.iAggLayerSwitch, end):
			for i in range(0, end):
				for j in range(0, end):
					self.addLink(
						self.AggSwitchList[x+i], self.EdgeSwitchList[x+j],
						bw=bw_a2e, cls=TCLink,max_queue_size=1000)   # use_htb=False

		# Edge to Host
		for x in range(0, self.iEdgeLayerSwitch):
			for i in range(0, int(self.density)):
				self.addLink(
					self.EdgeSwitchList[x],
					self.HostList[int(self.density * x + i)],
					bw=bw_e2h, cls=TCLink,max_queue_size=1000)   # use_htb=False

	def set_ovs_protocol_13(self,):
		"""
			Set the OpenFlow version for switches.
		"""
		self._set_ovs_protocol_13(self.CoreSwitchList)
		self._set_ovs_protocol_13(self.AggSwitchList)
		self._set_ovs_protocol_13(self.EdgeSwitchList)

	def _set_ovs_protocol_13(self, sw_list):
		for sw in sw_list:
			cmd = "sudo ovs-vsctl set bridge %s protocols=OpenFlow13" % sw
			os.system(cmd)
def set_host_ip(net, topo):
	hostlist = []
	for k in range(len(topo.HostList)):
		hostlist.append(net.get(topo.HostList[k]))
	i = 1
	j = 1
	for host in hostlist:
		host.setIP("10.%d.0.%d" % (i, j))
		j += 1
		if j == topo.density+1:
			j = 1
			i += 1
def create_subnetList(topo, num):
	"""
		Create the subnet list of the certain Pod.
	"""
	subnetList = []
	remainder = num % (topo.pod/2)
	if topo.pod == 4:
		if remainder == 0:
			subnetList = [num-1, num]
		elif remainder == 1:
			subnetList = [num, num+1]
		else:
			pass
	elif topo.pod == 8:
		if remainder == 0:
			subnetList = [num-3, num-2, num-1, num]
		elif remainder == 1:
			subnetList = [num, num+1, num+2, num+3]
		elif remainder == 2:
			subnetList = [num-1, num, num+1, num+2]
		elif remainder == 3:
			subnetList = [num-2, num-1, num, num+1]
		else:
			pass
	else:
		pass
	return subnetList
def install_proactive(net, topo):
	"""
		Install proactive flow entries for switches.
	"""
	# Edge Switch
	for sw in topo.EdgeSwitchList:
		num = int(sw[-2:])

		# Downstream
		for i in range(1, int(topo.density+1)):
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=40,arp, \
				nw_dst=10.%d.0.%d,actions=output:%d'" % (sw, num, i, topo.pod/2+i)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=40,ip, \
				nw_dst=10.%d.0.%d,actions=output:%d'" % (sw, num, i, topo.pod/2+i)
			os.system(cmd)

		# Upstream
		if topo.pod == 4:
			cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=1,type=select,bucket=output:1,bucket=output:2'" % sw
		elif topo.pod == 8:
			cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=1,type=select,bucket=output:1,bucket=output:2,\
			bucket=output:3,bucket=output:4'" % sw
		else:
			pass
		os.system(cmd)
		cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
		'table=0,priority=10,arp,actions=group:1'" % sw
		os.system(cmd)
		cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
		'table=0,priority=10,ip,actions=group:1'" % sw
		os.system(cmd)

	# Aggregate Switch
	for sw in topo.AggSwitchList:
		num = int(sw[-2:])
		subnetList = create_subnetList(topo, num)

		# Downstream
		k = 1
		for i in subnetList:
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=40,arp, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, topo.pod/2+k)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=40,ip, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, topo.pod/2+k)
			os.system(cmd)
			k += 1

		# Upstream
		if topo.pod == 4:
			cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=1,type=select,bucket=output:1,bucket=output:2'" % sw
		elif topo.pod == 8:
			cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=1,type=select,bucket=output:1,bucket=output:2,\
			bucket=output:3,bucket=output:4'" % sw
		else:
			pass
		os.system(cmd)
		cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
		'table=0,priority=10,arp,actions=group:1'" % sw
		os.system(cmd)
		cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
		'table=0,priority=10,ip,actions=group:1'" % sw
		os.system(cmd)

	# Core Switch
	for sw in topo.CoreSwitchList:
		j = 1
		k = 1
		for i in range(1, len(topo.EdgeSwitchList)+1):
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, j)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, j)
			os.system(cmd)
			k += 1
			if k == topo.pod/2 + 1:
				j += 1
				k = 1
def normal_traffic(net):
	host_list=[]
	for j in range(1,17):
		if j< 10:
			host_list.append('h00'+str(j))
		else:
			host_list.append('h0'+str(j))

	for i in range(len(host_list)):
		command="bash /home/ryu/sdncode/ecmp/ecmp_flows/%d.sh &" % (i + 1)
		host=net.get(host_list[i])
		host.cmd(command)
def calc_thoughput(fname):
	with open(fname,'r') as f:
		message=f.readlines()
		message_list=[]
		for mess in message:
			message_list.append(mess.split('-'))
		throughput={}
		for info in message_list:
			if info[1].startswith('3'):
				if info[2]=='eth3' or info[2] == 'eth4':
					key=int(info[0].split('.')[0])
					if key not in throughput.keys():
						throughput[key]=float(info[3])
					else:
						throughput[key]+=float(info[3])
		duration= len(throughput)-1
		output=0
		for v in throughput.values():
			output+=v
		print('平均吞吐率：',(round(output/duration/1024/1024*8)))
		print('标准化平均吞吐率：',(round(output / duration / 1024 / 1024 * 8)/160))
def bwm(fname):
	cmd = "bwm-ng -t %s -o csv -u bits -T rate -C '-' > %s" % (1000, fname)
	Popen(cmd,shell=True)
def traffic_generation(net):
	"""
		Generate traffics and test the performance of the network.
	"""
	# 1. Start iperf. (Elephant flows)
	peers=iperf_peers.peers
	port = 5202
	fname='/home/ryu/monitor_info/ecmp/throughput'
	for peer in peers:
		client = peer[0]
		server = peer[1]
		# Start the servers.
		server_Args = net.get(server)
		client_Args = net.get(client)
		server_Args.cmd("iperf3 -s -p %d &"%port)
		# Start the clients.
		info('*** IperfTest: Client: %s ==> Server: %s  \n' % (client, server))
		client_Args.cmd('iperf3 -c %s -u -b 10m -p %d -t 1000  > /dev/null &'%(server_Args.IP(),port))
		time.sleep(0.1)
		port+=1
	#等待流量稳定10s
	print('=======等待流量稳定30s=======')
	time.sleep(30)
	print('=======开启监控子进程=======')
	monitor = Process(target=bwm(fname=fname))
	monitor.start()
	time.sleep(60)
	monitor.terminate()
	print('=======关闭监控子进程=======')
	os.system('sudo killall bwm-ng')
	os.system('sudo killall iperf3')
	print('=========监控结束==========')
	calc_thoughput(fname=fname)
def run_experiment(pod, density, ip="127.0.0.1", port=6653, bw_c2a=10, bw_a2e=10, bw_e2h=10):
	Test_name='ecmp'
	topo = Fattree(pod, density)
	topo.createNodes()
	topo.createLinks(bw_c2a=bw_c2a, bw_a2e=bw_a2e, bw_e2h=bw_e2h)
	# 1. Start Mininet
	CONTROLLER_IP = ip
	CONTROLLER_PORT = port
	net = Mininet(topo=topo, link=TCLink, controller=None, autoSetMacs=True)
	net.addController(
		'controller', controller=RemoteController,
		ip=CONTROLLER_IP, port=CONTROLLER_PORT)
	net.start()

	# Set the OpenFlow version for switches as 1.3.0.
	topo.set_ovs_protocol_13()
	# Set the IP addresses for hosts.
	set_host_ip(net, topo)
	# Install proactive flow entries.
	install_proactive(net, topo)
	# 2. Generate traffics and test the performance of the network.
	info('*** Input Command : ')
	CommandList=['a','pingall','cli','q','ping']
	times=0
	Args=input().split()
	while True:
		if len(Args)==1:
			if Args[0] == 'pingall':
				info('*** >>>>>Command: %s Processing<<<<<\n' % Args[0].upper())
				net.pingAll()
				info('*** Command : ')
				Args = input().split()
			if Args[0] == 'cli':
				info('*** >>>>>Command: %s Processing<<<<<\n' % Args[0].upper())
				CLI(net)
				break
			if Args[0] == 'q':
				info('*** >>>>>Command: %s Processing<<<<<\n' % Args[0].upper())
				net.stop()
				break
			if Args[0] not in CommandList:
				info('*** >>>>>Wrong Command<<<<<\n')
				info('*** Command : ')
				Args = input().split()
		if Args[0] == 'a':
			info('*** >>>>>Command: %s Processing<<<<<\n' % Args[0].upper())
			traffic_generation(net=net)
			info('*** Command : ')
			Args = input().split()
		if Args[0] == 'ping':
			info('*** >>>>>Command: %s Processing<<<<<\n' % Args[0].upper())
			normal_traffic(net=net)
			info('*** >>>>>Normal_Traffic Has Been Injected<<<<<\n: ')
			info('*** Command : ')
			Args = input().split()
		if Args[0] not in CommandList:
			info('*** Command : ')
			Args = input().split()

if __name__ == '__main__':
	setLogLevel('info')
		# run_experiment(4, 2) or run_experiment(8, 4)
	run_experiment(4,2)
