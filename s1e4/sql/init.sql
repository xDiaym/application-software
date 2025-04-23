create table if not exists logs(
  id integer primary key autoincrement,
  dev_id integer not null references devices(id) on delete cascade,
  -- (C)reated, (T)erminated, (R)uning, (W)aiting
  status char(1) not null check(status in ('C', 'T', 'R', 'W')),
  created_ts datetime default current_timestamp not null
);

create table if not exists devices(
  id integer primary key autoincrement,
  name varchar(4) unique not null
);
