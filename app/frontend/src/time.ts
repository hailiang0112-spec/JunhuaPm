// 时间一律按北京时间显示（NFR-008），不随访问设备的时区变化。
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";

dayjs.extend(utc);
dayjs.extend(timezone);

/** 把服务端时间戳（或当前时刻）转为北京时间的 dayjs 对象 */
export const bj = (s?: string | null) => (s ? dayjs(s) : dayjs()).tz("Asia/Shanghai");
