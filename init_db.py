from db import create_tables, seed_vacancies

if __name__ == "__main__":
    create_tables()
    seed_vacancies()
    print("База создана, тестовые вакансии добавлены.")