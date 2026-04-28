use env_logger;
use log;

fn main() {
    std::env::set_var("RUST_LOG", "info");
    env_logger::init();
    log::info!("Starting application...");
    app_lib::run();
}
