#ifndef G13_BEAR_M15_ORACLE_MQH
#define G13_BEAR_M15_ORACLE_MQH

void BuildG13BearM15Oracle(EngineBar &bars[],const int spread_points)
  {
   ArrayResize(bars,50);
   SetBearHarnessBar(
      bars[0],PERIOD_M15,D'2026.08.18 04:45:00',
      4414.5300000000,4416.1600000000,
      4410.4800000000,4411.7400000000,0);
   bars[0].spread_points=spread_points;
   SetBearHarnessBar(
      bars[1],PERIOD_M15,D'2026.08.18 05:00:00',
      4411.8500000000,4414.8300000000,
      4409.7700000000,4414.6800000000,1);
   bars[1].spread_points=spread_points;
   SetBearHarnessBar(
      bars[2],PERIOD_M15,D'2026.08.18 05:15:00',
      4414.6900000000,4421.7700000000,
      4414.6900000000,4420.2700000000,2);
   bars[2].spread_points=spread_points;
   SetBearHarnessBar(
      bars[3],PERIOD_M15,D'2026.08.18 05:30:00',
      4420.2200000000,4422.8700000000,
      4419.9400000000,4422.7300000000,3);
   bars[3].spread_points=spread_points;
   SetBearHarnessBar(
      bars[4],PERIOD_M15,D'2026.08.18 05:45:00',
      4422.6300000000,4425.8600000000,
      4421.5600000000,4425.7300000000,4);
   bars[4].spread_points=spread_points;
   SetBearHarnessBar(
      bars[5],PERIOD_M15,D'2026.08.18 06:00:00',
      4425.7400000000,4429.8200000000,
      4418.9400000000,4421.6200000000,5);
   bars[5].spread_points=spread_points;
   SetBearHarnessBar(
      bars[6],PERIOD_M15,D'2026.08.18 06:15:00',
      4421.5700000000,4431.5400000000,
      4420.8400000000,4431.3800000000,6);
   bars[6].spread_points=spread_points;
   SetBearHarnessBar(
      bars[7],PERIOD_M15,D'2026.08.18 06:30:00',
      4431.3500000000,4433.4800000000,
      4428.3300000000,4429.5300000000,7);
   bars[7].spread_points=spread_points;
   SetBearHarnessBar(
      bars[8],PERIOD_M15,D'2026.08.18 06:45:00',
      4429.5700000000,4434.9500000000,
      4428.5500000000,4434.5700000000,8);
   bars[8].spread_points=spread_points;
   SetBearHarnessBar(
      bars[9],PERIOD_M15,D'2026.08.18 07:00:00',
      4434.7200000000,4436.1200000000,
      4428.6200000000,4429.2200000000,9);
   bars[9].spread_points=spread_points;
   SetBearHarnessBar(
      bars[10],PERIOD_M15,D'2026.08.18 07:15:00',
      4429.1800000000,4430.7300000000,
      4420.1000000000,4424.9300000000,10);
   bars[10].spread_points=spread_points;
   SetBearHarnessBar(
      bars[11],PERIOD_M15,D'2026.08.18 07:30:00',
      4424.9400000000,4426.1700000000,
      4411.8600000000,4411.8600000000,11);
   bars[11].spread_points=spread_points;
   SetBearHarnessBar(
      bars[12],PERIOD_M15,D'2026.08.18 07:45:00',
      4411.8300000000,4412.2000000000,
      4404.2100000000,4408.0100000000,12);
   bars[12].spread_points=spread_points;
   SetBearHarnessBar(
      bars[13],PERIOD_M15,D'2026.08.18 08:00:00',
      4407.9900000000,4408.2000000000,
      4398.4100000000,4400.9700000000,13);
   bars[13].spread_points=spread_points;
   SetBearHarnessBar(
      bars[14],PERIOD_M15,D'2026.08.18 08:15:00',
      4400.9600000000,4405.4600000000,
      4400.3300000000,4402.2500000000,14);
   bars[14].spread_points=spread_points;
   SetBearHarnessBar(
      bars[15],PERIOD_M15,D'2026.08.18 08:30:00',
      4402.2000000000,4402.6700000000,
      4394.1200000000,4394.9600000000,15);
   bars[15].spread_points=spread_points;
   SetBearHarnessBar(
      bars[16],PERIOD_M15,D'2026.08.18 08:45:00',
      4395.0100000000,4400.4200000000,
      4394.2500000000,4399.7700000000,16);
   bars[16].spread_points=spread_points;
   SetBearHarnessBar(
      bars[17],PERIOD_M15,D'2026.08.18 09:00:00',
      4399.7400000000,4403.9900000000,
      4398.8600000000,4401.4900000000,17);
   bars[17].spread_points=spread_points;
   SetBearHarnessBar(
      bars[18],PERIOD_M15,D'2026.08.18 09:15:00',
      4401.5100000000,4402.0800000000,
      4394.3100000000,4397.0600000000,18);
   bars[18].spread_points=spread_points;
   SetBearHarnessBar(
      bars[19],PERIOD_M15,D'2026.08.18 09:30:00',
      4397.0700000000,4397.0800000000,
      4394.4600000000,4394.7000000000,19);
   bars[19].spread_points=spread_points;
   SetBearHarnessBar(
      bars[20],PERIOD_M15,D'2026.08.18 09:45:00',
      4394.7100000000,4394.9800000000,
      4390.5700000000,4391.8300000000,20);
   bars[20].spread_points=spread_points;
   SetBearHarnessBar(
      bars[21],PERIOD_M15,D'2026.08.18 10:00:00',
      4391.8500000000,4392.6500000000,
      4389.7900000000,4392.2000000000,21);
   bars[21].spread_points=spread_points;
   SetBearHarnessBar(
      bars[22],PERIOD_M15,D'2026.08.18 10:15:00',
      4392.2600000000,4393.5800000000,
      4390.5800000000,4392.3400000000,22);
   bars[22].spread_points=spread_points;
   SetBearHarnessBar(
      bars[23],PERIOD_M15,D'2026.08.18 10:30:00',
      4392.3300000000,4394.2400000000,
      4388.8200000000,4393.3700000000,23);
   bars[23].spread_points=spread_points;
   SetBearHarnessBar(
      bars[24],PERIOD_M15,D'2026.08.18 10:45:00',
      4393.3400000000,4395.3600000000,
      4392.0700000000,4393.4700000000,24);
   bars[24].spread_points=spread_points;
   SetBearHarnessBar(
      bars[25],PERIOD_M15,D'2026.08.18 11:00:00',
      4393.4500000000,4394.0000000000,
      4390.7800000000,4391.1800000000,25);
   bars[25].spread_points=spread_points;
   SetBearHarnessBar(
      bars[26],PERIOD_M15,D'2026.08.18 11:15:00',
      4391.2300000000,4395.8500000000,
      4391.0300000000,4391.2800000000,26);
   bars[26].spread_points=spread_points;
   SetBearHarnessBar(
      bars[27],PERIOD_M15,D'2026.08.18 11:30:00',
      4390.9300000000,4393.9100000000,
      4386.0700000000,4393.5000000000,27);
   bars[27].spread_points=spread_points;
   SetBearHarnessBar(
      bars[28],PERIOD_M15,D'2026.08.18 11:45:00',
      4393.6100000000,4397.4600000000,
      4392.8800000000,4394.2800000000,28);
   bars[28].spread_points=spread_points;
   SetBearHarnessBar(
      bars[29],PERIOD_M15,D'2026.08.18 12:00:00',
      4394.2700000000,4395.2900000000,
      4387.5500000000,4395.2400000000,29);
   bars[29].spread_points=spread_points;
   SetBearHarnessBar(
      bars[30],PERIOD_M15,D'2026.08.18 12:15:00',
      4395.2400000000,4399.6800000000,
      4393.4700000000,4399.3600000000,30);
   bars[30].spread_points=spread_points;
   SetBearHarnessBar(
      bars[31],PERIOD_M15,D'2026.08.18 12:30:00',
      4399.3800000000,4400.1200000000,
      4395.1200000000,4397.0900000000,31);
   bars[31].spread_points=spread_points;
   SetBearHarnessBar(
      bars[32],PERIOD_M15,D'2026.08.18 12:45:00',
      4397.1100000000,4399.2700000000,
      4397.1100000000,4398.8700000000,32);
   bars[32].spread_points=spread_points;
   SetBearHarnessBar(
      bars[33],PERIOD_M15,D'2026.08.18 13:00:00',
      4398.8500000000,4400.8100000000,
      4396.8100000000,4397.5600000000,33);
   bars[33].spread_points=spread_points;
   SetBearHarnessBar(
      bars[34],PERIOD_M15,D'2026.08.18 13:15:00',
      4397.5300000000,4403.3700000000,
      4397.4100000000,4403.0000000000,34);
   bars[34].spread_points=spread_points;
   SetBearHarnessBar(
      bars[35],PERIOD_M15,D'2026.08.18 13:30:00',
      4403.1200000000,4403.5600000000,
      4396.2900000000,4401.4600000000,35);
   bars[35].spread_points=spread_points;
   SetBearHarnessBar(
      bars[36],PERIOD_M15,D'2026.08.18 13:45:00',
      4401.5400000000,4402.5800000000,
      4395.4200000000,4395.5400000000,36);
   bars[36].spread_points=spread_points;
   SetBearHarnessBar(
      bars[37],PERIOD_M15,D'2026.08.18 14:00:00',
      4395.8500000000,4396.0900000000,
      4387.8900000000,4392.6000000000,37);
   bars[37].spread_points=spread_points;
   SetBearHarnessBar(
      bars[38],PERIOD_M15,D'2026.08.18 14:15:00',
      4392.5300000000,4393.4800000000,
      4386.8100000000,4389.2900000000,38);
   bars[38].spread_points=spread_points;
   SetBearHarnessBar(
      bars[39],PERIOD_M15,D'2026.08.18 14:30:00',
      4389.1500000000,4398.5200000000,
      4389.0400000000,4396.5500000000,39);
   bars[39].spread_points=spread_points;
   SetBearHarnessBar(
      bars[40],PERIOD_M15,D'2026.08.18 14:45:00',
      4396.5300000000,4396.8400000000,
      4391.4500000000,4393.2100000000,40);
   bars[40].spread_points=spread_points;
   SetBearHarnessBar(
      bars[41],PERIOD_M15,D'2026.08.18 15:00:00',
      4393.1200000000,4393.7500000000,
      4391.0200000000,4392.6100000000,41);
   bars[41].spread_points=spread_points;
   SetBearHarnessBar(
      bars[42],PERIOD_M15,D'2026.08.18 15:15:00',
      4392.6300000000,4392.6600000000,
      4388.5900000000,4389.2700000000,42);
   bars[42].spread_points=spread_points;
   SetBearHarnessBar(
      bars[43],PERIOD_M15,D'2026.08.18 15:30:00',
      4389.1400000000,4394.9000000000,
      4387.3100000000,4388.4600000000,43);
   bars[43].spread_points=spread_points;
   SetBearHarnessBar(
      bars[44],PERIOD_M15,D'2026.08.18 15:45:00',
      4388.4100000000,4394.9600000000,
      4386.9300000000,4393.2800000000,44);
   bars[44].spread_points=spread_points;
   SetBearHarnessBar(
      bars[45],PERIOD_M15,D'2026.08.18 16:00:00',
      4393.2900000000,4395.6500000000,
      4392.2600000000,4394.4100000000,45);
   bars[45].spread_points=spread_points;
   SetBearHarnessBar(
      bars[46],PERIOD_M15,D'2026.08.18 16:15:00',
      4394.4200000000,4396.1100000000,
      4389.7400000000,4392.0000000000,46);
   bars[46].spread_points=spread_points;
   SetBearHarnessBar(
      bars[47],PERIOD_M15,D'2026.08.18 16:30:00',
      4391.9700000000,4398.5700000000,
      4391.6700000000,4398.5600000000,47);
   bars[47].spread_points=spread_points;
   SetBearHarnessBar(
      bars[48],PERIOD_M15,D'2026.08.18 16:45:00',
      4398.5400000000,4399.4700000000,
      4396.4300000000,4397.6300000000,48);
   bars[48].spread_points=spread_points;
   SetBearHarnessBar(
      bars[49],PERIOD_M15,D'2026.08.18 17:00:00',
      4397.7500000000,4399.0700000000,
      4391.9100000000,4393.4900000000,49);
   bars[49].spread_points=spread_points;
  }

#endif
